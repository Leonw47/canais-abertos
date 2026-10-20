#!/usr/bin/env python3
"""
Canais Abertos — TV ao vivo em português, só com fontes abertas e gratuitas.

Usa a lista pública do projeto iptv-org (canais em português) e mantém apenas transmissões
legítimas: emissoras nos próprios servidores (públicas, educativas, regionais, religiosas…) e
canais gratuitos oficiais com anúncios (Pluto TV, Samsung TV Plus e similares). Retransmissões
de TV paga (servidas de IPs soltos ou de domínios de retransmissão) ficam de fora.
"➕ Adicionar canal" guarda canais próprios (link, endereço de rede ou frequência da antena digital)
em "Meus canais"; esses não passam pelo filtro: a fonte é escolha de quem adiciona.

Uso:   python canais_abertos.py              abre o programa
       python canais_abertos.py --listar     mostra no terminal o que entra e o que sai do filtro
Dependências: VLC instalado (64 bits) + pip install python-vlc pillow
"""

import ipaddress
import json
import os
import queue
import re
import sys
import threading
import time
import unicodedata
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlparse

LISTA_URL = "https://iptv-org.github.io/iptv/languages/por.m3u"
DADOS = Path(os.environ.get("APPDATA", Path.home())) / "CanaisAbertos"
ARQ_LISTA = DADOS / "lista_por.m3u"
ARQ_ESTADO = DADOS / "estado.json"
ARQ_MEUS = DADOS / "meus_canais.json"
DIR_LOGOS = DADOS / "logos"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) CanaisAbertos/1.0"
VALIDADE_LISTA = 3 * 24 * 3600          # baixa a lista de novo a cada 3 dias
VALIDADE_TESTE = 6 * 3600               # resultado de "verificar canais" vale 6 h

CATEGORIAS = {
    "kids": "Infantil", "animation": "Desenhos e Animes", "news": "Notícias", "religious": "Religioso",
    "education": "Educativo", "legislative": "Governo e Legislativo", "general": "Variedades",
    "entertainment": "Entretenimento", "movies": "Filmes", "series": "Séries", "sports": "Esportes",
    "music": "Música", "documentary": "Documentários", "comedy": "Comédia", "outdoor": "Natureza e Aventura",
    "family": "Família", "culture": "Cultura", "cooking": "Culinária", "lifestyle": "Estilo de vida",
    "classic": "Clássicos", "travel": "Viagem", "auto": "Automóveis", "business": "Negócios",
    "science": "Ciência", "shop": "Compras", "public": "Públicos", "weather": "Tempo", "relax": "Relaxar",
    "undefined": "Outros",
}
INFANTIL = "Infantil"
MEUS = "Meus canais"

# Plataformas gratuitas oficiais (FAST). jmp2.uk é o redirecionador usado pelo iptv-org para elas.
JMP2 = {"plu": "Pluto TV", "sam": "Samsung TV Plus", "rak": "Rakuten TV", "plex": "Plex", "roku": "Roku",
        "stv": "Samsung TV Plus", "lg": "LG Channels"}
FAST_HOSTS = [
    (r"(^|\.)pluto\.tv$", "Pluto TV"), (r"samsung\.wurl\.(tv|com)$", "Samsung TV Plus"),
    (r"(^|\.)wurl\.(tv|com)$", "Canal gratuito"), (r"(^|\.)amagi\.tv$", "Canal gratuito"),
    (r"mediatailor\..*amazonaws\.com$", "Canal gratuito"), (r"fast\.jwp\.services$", "Canal gratuito"),
    (r"(^|\.)xumo\.", "Xumo"), (r"(^|\.)plex\.tv$", "Plex"), (r"(^|\.)runtime\.tv$", "Runtime"),
]
# Marcas de TV paga (ou da TV Globo, que só transmite ao vivo com login): só valem nas plataformas oficiais.
PAGA = re.compile(
    r"cartoon network|discovery|disney|dreamworks|gloob|tooncast|baby ?tv|jim ?jam|zoomoo|dum ?dum|box kids|"
    r"\bhbo\b|telecine|megapix|studio universal|universal (tv|channel)|warner|\btnt\b|\bspace\b|\bfox\b|star channel|\bespn|sportv|premiere|"
    r"combate|globo|\bgnt\b|multishow|\bviva\b|canal brasil|\bbis\b|history|a&e|\bamc\b|\baxn\b|\bsony\b|"
    r"\bnat ?geo|national geographic|animal planet|\btlc\b|\bhgtv\b|food network|lifetime|cinemax|"
    r"band ?sports|band ?news|arte ?1|curta!?|film ?& ?arts|studio universal|nickelodeon|nick ?jr|\bnick\b|"
    r"comedy central|\bmtv\b|paramount|\btbs\b|bloomberg|\bdazn|\bufc\b|\bnba\b|\bnfl\b", re.I)
# Domínios típicos de retransmissão (servidores que repassam canais pagos)
RETRANSMISSAO = re.compile(
    r"x1colegal|nxplay|aynascope|iptvperu|boldmss|onnethn|\.s\.gy$|dyndns|ddns|duckdns|no-ip|hopto|zapto|"
    r"freeddns|mcquack|clarovtr|vtrplay|redirect\.|\.xyz$|\.top$|(^|\.)github\.com$|githubusercontent\.com$", re.I)
RE_PLAY_RESTREAM = re.compile(r"/play/a[0-9a-z]{2,4}(/|$)", re.I)


def norm(s):
    return "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c)).lower()


@dataclass
class Transmissao:
    url: str
    qualidade: str
    fonte: str
    referrer: str = ""
    user_agent: str = ""
    nao_24h: bool = False
    geobloqueio: bool = False
    pluto_id: str = ""          # canais da Pluto TV: o endereço é montado na hora (a sessão expira)
    programa: str = ""          # antena: número do serviço quando a frequência carrega mais de um

    @property
    def id_teste(self):
        return f"pluto:{self.pluto_id}" if self.pluto_id else self.url


@dataclass
class Canal:
    chave: str
    nome: str
    logo: str
    categorias: list
    pais: str
    transmissoes: list = field(default_factory=list)
    resumo: str = ""

    @property
    def fonte(self):
        fs = []
        for t in self.transmissoes:
            if t.fonte not in fs:
                fs.append(t.fonte)
        return " / ".join(fs)

    @property
    def infantil(self):
        return INFANTIL in self.categorias


def fonte_legitima(nome, url):
    """(True, 'Pluto TV' | 'Emissora' | …) ou (False, motivo)."""
    try:
        p = urlparse(url)
    except ValueError:
        return False, "endereço inválido"
    host = (p.hostname or "").lower()
    if not host:
        return False, "endereço inválido"
    try:
        ipaddress.ip_address(host)
        return False, "servidor sem domínio (IP), típico de retransmissão"
    except ValueError:
        pass
    if host == "jmp2.uk":
        pref = p.path.strip("/").split("-")[0]
        return True, JMP2.get(pref, "Canal gratuito")
    for padrao, rotulo in FAST_HOSTS:
        if re.search(padrao, host):
            return True, rotulo
    if RETRANSMISSAO.search(host) or RE_PLAY_RESTREAM.search(p.path):
        return False, "domínio de retransmissão"
    if PAGA.search(nome):
        return False, "canal de TV paga fora de plataforma oficial"
    return True, "Emissora"


def _virgula_do_nome(ln):
    """Posição da vírgula que separa os atributos do nome (ignora vírgulas entre aspas)."""
    aspas = False
    for i, c in enumerate(ln):
        if c == '"':
            aspas = not aspas
        elif c == "," and not aspas:
            return i
    return -1


def ler_m3u(texto):
    """Lista de (atributos, nome, url, opções) a partir de um M3U."""
    itens, atual, opcoes = [], None, {}
    for ln in texto.splitlines():
        ln = ln.strip()
        if ln.startswith("#EXTINF"):
            v = _virgula_do_nome(ln)
            cab, nome = (ln[:v], ln[v + 1:].strip()) if v >= 0 else (ln, "")
            attrs = dict(re.findall(r'([\w-]+)="([^"]*)"', cab))
            atual = (attrs, nome)
            opcoes = {k: attrs[k] for k in ("http-referrer", "http-user-agent") if attrs.get(k)}
        elif ln.startswith("#EXTVLCOPT:"):
            k, _, v = ln[11:].partition("=")
            opcoes[k.strip().lower()] = v.strip()
        elif ln and not ln.startswith("#") and atual:
            itens.append((atual[0], atual[1], ln, opcoes))
            atual, opcoes = None, {}
    return itens


def limpar_nome(nome):
    nome = re.sub(r"\s*\(\d{3,4}[pi]\)|\s*\[[^\]]*\]", "", nome)
    nome = re.sub(r"\s*\((United States|Brazil|Brasil|Portugal|Latin America)\)", "", nome)
    return re.sub(r"\s+BR$", "", nome).strip()


def montar_canais(texto, motivos=None):
    canais = {}
    for attrs, nome_bruto, url, opcoes in ler_m3u(texto):
        grupos = [g.strip().lower() for g in (attrs.get("group-title") or "undefined").split(";") if g.strip()]
        if "xxx" in grupos:
            continue
        qualidade = (re.search(r"\((\d{3,4}[pi])\)", nome_bruto) or [None, ""])[1]
        nome = limpar_nome(nome_bruto)
        ok, fonte = fonte_legitima(nome, url)
        if not ok:
            if motivos is not None:
                motivos.append((nome, fonte, url))
            continue
        tvg = attrs.get("tvg-id", "")
        chave = tvg.split("@")[0] if tvg else norm(nome)
        pais = (chave.rsplit(".", 1)[-1].upper() if "." in chave else "")
        c = canais.get(chave)
        if c is None:
            c = canais[chave] = Canal(chave, nome, attrs.get("tvg-logo", ""),
                                      [CATEGORIAS.get(g, g.capitalize()) for g in grupos], pais)
        c.transmissoes.append(Transmissao(url, qualidade, fonte, opcoes.get("http-referrer", ""),
                                          opcoes.get("http-user-agent", ""), "Not 24/7" in nome_bruto,
                                          "Geo-blocked" in nome_bruto))
    for c in canais.values():   # melhor qualidade primeiro; geobloqueadas por último
        c.transmissoes.sort(key=lambda t: (t.geobloqueio, -int(re.sub(r"\D", "", t.qualidade) or 0)))
    return sorted(canais.values(), key=lambda c: norm(c.nome))


def baixar_lista(forcar=False):
    DADOS.mkdir(parents=True, exist_ok=True)
    if not forcar and ARQ_LISTA.exists() and time.time() - ARQ_LISTA.stat().st_mtime < VALIDADE_LISTA:
        return ARQ_LISTA.read_text(encoding="utf-8")
    req = urllib.request.Request(LISTA_URL, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=30) as r:
        texto = r.read().decode("utf-8", "replace")
    if "#EXTINF" not in texto:
        raise RuntimeError("a lista baixada veio vazia")
    ARQ_LISTA.write_text(texto, encoding="utf-8")
    return texto


# ═══════════════════════════════════════════════════════════════════════════════
# PLUTO TV BRASIL — grade oficial e gratuita, direto da API pública que o site pluto.tv usa
# ═══════════════════════════════════════════════════════════════════════════════

PLUTO_GUIA = "https://service-channels.clusters.pluto.tv/v2/guide"
CATEG_PLUTO = {"Infantil": [INFANTIL], "Nickelodeon": [INFANTIL, "Nickelodeon"], "Anime": ["Desenhos e Animes"],
               "South Park": ["Desenhos e Animes", "Comédia"], "Natureza": ["Natureza e Aventura"],
               "Estilo de Vida": ["Estilo de vida"], "Curiosidades": ["Documentários"]}


def _json(url, headers=None, timeout=20):
    req = urllib.request.Request(url, headers={"User-Agent": UA, **(headers or {})})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


class Pluto:
    def __init__(self, client_id):
        self.client_id = client_id
        self.boot, self.t_boot = None, 0
        self.trava = threading.Lock()

    def sessao(self, forcar=False):
        with self.trava:
            validade = (self.boot or {}).get("refreshInSec", 28800) - 600
            if forcar or not self.boot or time.time() - self.t_boot > validade:
                from urllib.parse import urlencode
                q = urlencode({"appName": "web", "appVersion": "9.0.0", "deviceVersion": "129.0.0",
                               "deviceModel": "web", "deviceMake": "chrome", "deviceType": "web",
                               "clientID": self.client_id, "clientModelNumber": "1.0.0",
                               "serverSideAds": "true"})   # anúncios embutidos, como no site: é o que mantém o serviço grátis
                self.boot = _json("https://boot.pluto.tv/v4/start?" + q)
                self.t_boot = time.time()
            return self.boot

    def _auth(self):
        return {"Authorization": f"Bearer {self.sessao()['sessionToken']}"}

    def url(self, pid):
        b = self.sessao()
        return (f"{b['servers']['stitcher']}/v2/stitch/hls/channel/{pid}/master.m3u8?"
                f"{b['stitcherParams']}&jwt={b['sessionToken']}&masterJWTPassthrough=true")

    def canais(self):
        cats = _json(f"{PLUTO_GUIA}/categories", self._auth()).get("data", [])
        lista = _json(f"{PLUTO_GUIA}/channels?channelIds=&offset=0&limit=1000&sort=number%3Aasc",
                      self._auth()).get("data", [])
        cat_de = {}
        for c in cats:
            for cid in c.get("channelIDs", []):
                cat_de.setdefault(cid, []).extend(CATEG_PLUTO.get(c.get("name", ""), [c.get("name", "")]))
        saida = []
        for ch in lista:
            if not ch.get("isStitched", True) or ch.get("plutoOfficeOnly"):
                continue
            logo = next((i["url"] for i in ch.get("images", []) if i.get("type") == "colorLogoPNG"), "")
            categorias = list(dict.fromkeys(cat_de.get(ch["id"], ["Outros"])))
            c = Canal(f"pluto.{ch.get('slug') or ch['id']}", ch["name"], logo, categorias, "BR")
            c.transmissoes.append(Transmissao("", "", "Pluto TV", pluto_id=ch["id"]))
            c.resumo = ch.get("summary", "")
            saida.append(c)
        return saida

    def agora(self, pid):
        """[(início, fim, título)] do que está passando e do que vem depois."""
        from datetime import datetime, timezone
        ini = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:00.000Z")
        d = _json(f"{PLUTO_GUIA}/timelines?start={ini}&channelIds={pid}&duration=240", self._auth(), 10)
        out = []
        for item in d.get("data", []):
            for p in item.get("timelines", [])[:2]:
                out.append((p.get("start", ""), p.get("stop", ""), p.get("title", "")))
        return out


def carregar_tudo(pluto, forcar=False):
    """Pluto TV Brasil (oficial) + emissoras da lista iptv-org. Devolve (canais, aviso)."""
    aviso = ""
    try:
        texto = baixar_lista(forcar)
    except Exception as e:
        if not ARQ_LISTA.exists():
            raise
        texto = ARQ_LISTA.read_text(encoding="utf-8")
        aviso = f"Sem internet para atualizar a lista ({e}); usando a salva."
    canais = montar_canais(texto)
    try:
        do_pluto = pluto.canais()
    except Exception as e:
        do_pluto = []
        aviso = (aviso + " " if aviso else "") + f"Pluto TV indisponível agora ({e}); usando os links da lista."
    if do_pluto:
        # a grade oficial substitui os links antigos da Pluto que vêm na lista (alguns já não abrem)
        for c in canais:
            c.transmissoes = [t for t in c.transmissoes if t.fonte != "Pluto TV"]
        canais = [c for c in canais if c.transmissoes] + do_pluto
    return sorted(canais, key=lambda c: norm(c.nome)), aviso


# ═══════════════════════════════════════════════════════════════════════════════
# MEUS CANAIS — adicionados à mão (link, endereço de rede ou antena digital)
# ═══════════════════════════════════════════════════════════════════════════════

ESQUEMAS = {"http", "https", "rtmp", "rtmps", "rtsp", "rtp", "udp", "mms", "mmsh", "srt", "isdb-t"}


def normalizar_endereco(txt):
    """Link ou endereço digitado → endereço que o VLC abre. ValueError se não der para usar."""
    s = txt.strip().strip('"').strip()
    if not s:
        raise ValueError("Informe o link ou o endereço do canal.")
    if " " in s:
        raise ValueError("O endereço não pode ter espaços.")
    if "://" in s:
        esquema = s.split("://", 1)[0].lower()
        if esquema not in ESQUEMAS:
            raise ValueError(f"Tipo de endereço não suportado: {esquema}://")
        return s
    if s.startswith("@"):                       # udp multicast escrito do jeito do VLC
        return "udp://" + s
    host = re.split(r"[:/]", s, maxsplit=1)[0]
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        if "." not in host:
            raise ValueError("Não reconheci o endereço. Exemplos: https://site.com/aovivo.m3u8 · "
                             "192.168.0.20:8080/stream · udp://@239.0.0.1:1234")
        return "https://" + s                   # domínio sem http(s): hoje quase tudo é https
    return ("udp://@" if ip.is_multicast else "http://") + s


def frequencia_hz(txt):
    """Canal físico ('28') ou frequência em MHz ('557,142') → Hz da TV digital brasileira (ISDB-T, 6 MHz)."""
    s = txt.strip().lower().replace("mhz", "").replace(",", ".").strip()
    try:
        v = float(s)
    except ValueError:
        raise ValueError("Use o canal físico (ex.: 28) ou a frequência em MHz (ex.: 557,142).") from None
    if v.is_integer() and 7 <= v <= 13:          # VHF alto
        mhz = 177 + 1 / 7 + (v - 7) * 6
    elif v.is_integer() and 14 <= v <= 69:       # UHF
        mhz = 473 + 1 / 7 + (v - 14) * 6
    elif 170 <= v <= 900:
        mhz = v
    elif v < 70:
        raise ValueError(f"“{txt.strip()}” parece o número que aparece na TV (canal virtual). Aqui vai o canal "
                         "físico (7 a 69) ou a frequência em MHz.")
    else:
        raise ValueError("Canal físico vai de 7 a 69; frequência, de 170 a 900 MHz.")
    return round(mhz * 1_000_000)


def ler_meus():
    try:
        return [d for d in json.loads(ARQ_MEUS.read_text(encoding="utf-8")) if d.get("url")]
    except Exception:
        return []


def salvar_meus(lista):
    DADOS.mkdir(parents=True, exist_ok=True)
    ARQ_MEUS.write_text(json.dumps(lista, ensure_ascii=False, indent=1), encoding="utf-8")


def canal_meu(d):
    cats = [d.get("categoria") or MEUS]
    if MEUS not in cats:
        cats.append(MEUS)
    if d.get("infantil") and INFANTIL not in cats:
        cats.insert(0, INFANTIL)
    c = Canal(f"meu.{d['id']}", d["nome"], "", cats, "")
    c.transmissoes.append(Transmissao(d["url"], "", "Antena" if d.get("tipo") == "antena" else "Meu canal",
                                      d.get("referrer", ""), d.get("user_agent", ""), programa=d.get("programa", "")))
    return c


def testar_transmissao(t, pluto=None):
    """True se o endereço responde com um vídeo/playlist (só lê o começo); None se não dá para testar
    sem abrir o vídeo (antena, udp, rtsp…)."""
    if not t.pluto_id and urlparse(t.url).scheme.lower() not in ("http", "https"):
        return None
    hdr = {"User-Agent": t.user_agent or UA}
    if t.referrer:
        hdr["Referer"] = t.referrer
    try:
        url = pluto.url(t.pluto_id) if t.pluto_id and pluto else t.url
        req = urllib.request.Request(url, headers=hdr)
        with urllib.request.urlopen(req, timeout=8) as r:
            ini = r.read(2048)
            return r.status < 400 and len(ini) > 0
    except Exception:
        return False


class Estado:
    def __init__(self):
        self.d = {"favoritos": [], "volume": 70, "ultimo": "", "modo_criancas": False,
                  "esconder_fora": False, "testes": {}, "geometria": ""}
        try:
            self.d.update(json.loads(ARQ_ESTADO.read_text(encoding="utf-8")))
        except Exception:
            pass
        if not self.d.get("id_aparelho"):
            import uuid
            self.d["id_aparelho"] = str(uuid.uuid4())     # a Pluto TV pede um identificador do aparelho

    def salvar(self):
        DADOS.mkdir(parents=True, exist_ok=True)
        ARQ_ESTADO.write_text(json.dumps(self.d, ensure_ascii=False, indent=1), encoding="utf-8")

    def no_ar(self, url):
        """True/False pelo último teste (se recente) ou None."""
        r = self.d["testes"].get(url)
        if not r or time.time() - r[1] > VALIDADE_TESTE:
            return None
        return r[0]


# ═══════════════════════════════════════════════════════════════════════════════
# JANELA
# ═══════════════════════════════════════════════════════════════════════════════

BG, BG2, BG3 = "#1e1e2e", "#2a2a3e", "#16162a"
ACCENT, ACCENT2 = "#7c6af7", "#5a4fd1"
FG, FG2, OK, ERRO, AVISO, BTN = "#e0e0f0", "#9999bb", "#50fa7b", "#ff5555", "#f1fa8c", "#3d3d5c"
KIDS = "#ffb86c"
FONT, FONT_B, FONT_H = ("Segoe UI", 10), ("Segoe UI", 10, "bold"), ("Segoe UI", 12, "bold")


def _recurso(nome):
    """Arquivo que vai junto do programa (no .exe fica dentro do pacote)."""
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    return base / nome


def _preparar_vlc_embutido():
    # No .exe o motor do VLC vai junto (pasta vlc/): funciona sem o VLC instalado no computador.
    pasta = _recurso("vlc")
    if (pasta / "libvlc.dll").exists():
        os.add_dll_directory(str(pasta))
        os.environ["PYTHON_VLC_LIB_PATH"] = str(pasta / "libvlc.dll")
        os.environ["PYTHON_VLC_MODULE_PATH"] = str(pasta / "plugins")
        os.environ["VLC_PLUGIN_PATH"] = str(pasta / "plugins")


def app():
    import tkinter as tk
    from tkinter import ttk, messagebox
    _preparar_vlc_embutido()
    try:
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("CanaisAbertos.App")   # ícone próprio na barra
    except Exception:
        pass
    try:
        import vlc
    except Exception:
        tk.Tk().withdraw()
        messagebox.showerror("Canais Abertos", "Falta o componente de vídeo.\n\nInstale com:\n"
                                               "python -m pip install python-vlc\n\ne o VLC 64 bits (videolan.org).")
        return
    try:
        from PIL import Image, ImageTk
    except Exception:
        Image = ImageTk = None

    class App(tk.Tk):
        def __init__(self):
            super().__init__()
            self.title("Canais Abertos — TV ao vivo em português")
            self.configure(bg=BG)
            if _recurso("canais_abertos.ico").exists():
                try:
                    self.iconbitmap(default=str(_recurso("canais_abertos.ico")))
                except Exception:
                    pass
            self.minsize(980, 600)
            self.est = Estado()
            self.pluto = Pluto(self.est.d["id_aparelho"])
            self.pluto_refeito = False
            self.geometry(self.est.d.get("geometria") or "1280x760")
            self.base, self.canais, self.visiveis = [], [], []     # base = catálogo; canais = catálogo + meus
            self.atual, self.idx_trans, self.t_inicio = None, 0, 0
            self.fila = queue.Queue()
            self.icones, self.logo_pedidos = {}, set()
            self.cheia = False

            self.inst = vlc.Instance("--quiet", "--network-caching=2500", "--no-video-title-show")
            self.player = self.inst.media_player_new()
            self._montar()
            self.player.audio_set_volume(int(self.est.d["volume"]))
            self.protocol("WM_DELETE_WINDOW", self.sair)
            self.after(100, self._carregar_lista)
            self.after(400, self._vigiar)
            self.after(150, self._processar_fila)
            if "--autoteste" in sys.argv:
                self._autoteste(sys.argv[sys.argv.index("--autoteste") + 1])

        def _autoteste(self, saida):
            """Confere o programa empacotado: carrega a lista, toca um canal infantil e grava o resultado."""
            self.withdraw()
            r = {"inicio": time.time(), "vlc": vlc.libvlc_get_version().decode(),
                 "vlc_embutido": bool(os.environ.get("PYTHON_VLC_LIB_PATH"))}
            estado = {"fase": "lista"}

            def passo():
                if estado["fase"] == "lista" and len(self.canais) > 100:
                    r["canais"] = len(self.canais)
                    r["infantis"] = sum(1 for c in self.canais if c.infantil)
                    alvo = next((c for c in self.canais if c.nome.startswith("Turma da M")),
                                next(c for c in self.canais if c.infantil))
                    r["canal"] = alvo.nome
                    self.tocar(alvo)
                    estado["fase"], estado["t"] = "tocando", time.time()
                elif estado["fase"] == "tocando":
                    if self.player.get_state() == vlc.State.Playing and not self.msg_video.winfo_ismapped():
                        r["tocou"] = True
                        r["segundos_ate_tocar"] = round(time.time() - estado["t"], 1)
                        estado["fase"] = "fim"
                    elif time.time() - estado["t"] > 40:
                        r["tocou"] = False
                        estado["fase"] = "fim"
                if estado["fase"] == "fim" or time.time() - r["inicio"] > 120:
                    r["status"] = self.status.cget("text")
                    Path(saida).write_text(json.dumps(r, ensure_ascii=False, indent=1), encoding="utf-8")
                    self.sair()
                    return
                self.after(300, passo)
            self.after(300, passo)

        # ---------- interface ----------
        def _btn(self, pai, texto, cmd, bg=BTN, fg=FG, font=FONT, **kw):
            return tk.Button(pai, text=texto, command=cmd, bg=bg, fg=fg, activebackground=ACCENT2,
                             activeforeground="white", relief=tk.FLAT, font=font, cursor="hand2",
                             padx=10, pady=3, **kw)

        def _montar(self):
            self.hdr = tk.Frame(self, bg=BG3, pady=10)
            self.hdr.pack(fill=tk.X)
            tk.Label(self.hdr, text="📺  Canais Abertos", bg=BG3, fg=ACCENT,
                     font=("Segoe UI", 16, "bold")).pack(side=tk.LEFT, padx=18)
            tk.Label(self.hdr, text="TV ao vivo em português — só emissoras e canais gratuitos oficiais",
                     bg=BG3, fg=FG2, font=FONT).pack(side=tk.LEFT)

            self.status = tk.Label(self, text="", bg=BG3, fg=FG2, font=("Segoe UI", 9), anchor="w", padx=10)
            self.status.pack(fill=tk.X, side=tk.BOTTOM)

            self.corpo = tk.Frame(self, bg=BG)
            self.corpo.pack(fill=tk.BOTH, expand=True)

            # coluna 1: busca, categorias, opções
            self.col1 = tk.Frame(self.corpo, bg=BG, width=210)
            self.col1.pack(side=tk.LEFT, fill=tk.Y, padx=(8, 4), pady=8)
            self.col1.pack_propagate(False)
            tk.Label(self.col1, text="Buscar canal", bg=BG, fg=FG2, font=FONT).pack(anchor="w")
            self.busca = tk.StringVar()
            self.busca.trace_add("write", lambda *_: self._filtrar())
            tk.Entry(self.col1, textvariable=self.busca, bg=BG2, fg=FG, insertbackground=FG, relief=tk.FLAT,
                     font=FONT).pack(fill=tk.X, pady=(2, 8), ipady=3)
            tk.Label(self.col1, text="Categorias", bg=BG, fg=FG2, font=FONT).pack(anchor="w")
            self.lb_cat = tk.Listbox(self.col1, bg=BG2, fg=FG, relief=tk.FLAT, font=FONT, activestyle="none",
                                     selectbackground=ACCENT, exportselection=False, highlightthickness=0)
            self.lb_cat.pack(fill=tk.BOTH, expand=True, pady=(2, 8))
            self.lb_cat.bind("<<ListboxSelect>>", lambda e: self._filtrar())
            self.v_criancas = tk.BooleanVar(value=bool(self.est.d.get("modo_criancas")))
            self.v_esconder = tk.BooleanVar(value=bool(self.est.d.get("esconder_fora")))
            for txt, var in (("🧸 Modo crianças (só infantis)", self.v_criancas),
                             ("Esconder canais fora do ar", self.v_esconder)):
                tk.Checkbutton(self.col1, text=txt, variable=var, command=self._opcoes, bg=BG, fg=FG,
                               selectcolor=BG2, activebackground=BG, activeforeground=FG, font=FONT,
                               anchor="w").pack(fill=tk.X)
            self.b_add = self._btn(self.col1, "➕ Adicionar canal", self.dialogo_canal, bg=ACCENT2)
            self.b_add.pack(fill=tk.X, pady=(8, 2))
            self._btn(self.col1, "🩺 Verificar canais no ar", self.verificar).pack(fill=tk.X, pady=2)
            self._btn(self.col1, "🔄 Atualizar lista", lambda: self._carregar_lista(True)).pack(fill=tk.X, pady=2)

            # coluna 2: canais
            self.col2 = tk.Frame(self.corpo, bg=BG, width=400)
            self.col2.pack(side=tk.LEFT, fill=tk.Y, padx=4, pady=8)
            self.col2.pack_propagate(False)
            self.lbl_lista = tk.Label(self.col2, text="Canais", bg=BG, fg=FG2, font=FONT, anchor="w")
            self.lbl_lista.pack(fill=tk.X)
            st = ttk.Style(self)
            st.theme_use("clam")
            st.configure("Canais.Treeview", background=BG2, fieldbackground=BG2, foreground=FG, rowheight=30,
                         font=FONT, borderwidth=0)
            st.map("Canais.Treeview", background=[("selected", ACCENT)], foreground=[("selected", "white")])
            st.configure("Canais.Treeview.Heading", background=BG3, foreground=FG2, font=("Segoe UI", 9))
            st.configure("Vertical.TScrollbar", background=BTN, troughcolor=BG2, arrowcolor=FG2)
            st.configure("TCombobox", fieldbackground=BG2, background=BTN, foreground=FG, arrowcolor=FG2,
                         insertcolor=FG, borderwidth=0)
            for k, v in (("background", BG2), ("foreground", FG), ("selectBackground", ACCENT)):
                self.option_add(f"*TCombobox*Listbox.{k}", v)
            fr = tk.Frame(self.col2, bg=BG)
            fr.pack(fill=tk.BOTH, expand=True, pady=(2, 0))
            self.tv = ttk.Treeview(fr, style="Canais.Treeview", columns=("fonte", "st"), show="tree headings",
                                   selectmode="browse")
            self.tv.heading("#0", text="Canal", anchor="w")
            self.tv.heading("fonte", text="Fonte", anchor="w")
            self.tv.heading("st", text="")
            self.tv.column("#0", width=255, stretch=True)
            self.tv.column("fonte", width=95, stretch=False)
            self.tv.column("st", width=26, stretch=False, anchor="center")
            sb = ttk.Scrollbar(fr, orient="vertical", command=self.tv.yview)
            self.tv.configure(yscrollcommand=sb.set)
            self.tv.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
            sb.pack(side=tk.RIGHT, fill=tk.Y)
            self.tv.tag_configure("infantil", foreground=KIDS)
            self.tv.tag_configure("fora", foreground="#77778f")
            self.tv.bind("<Double-1>", lambda e: self.tocar_selecionado())
            self.tv.bind("<Return>", lambda e: self.tocar_selecionado())
            self.tv.bind("<<TreeviewSelect>>", lambda e: self._carregar_logos_visiveis())
            self.tv.bind("<Button-3>", self._menu_canal)
            self.tv.bind("<Delete>", lambda e: self.tv.selection() and self.remover_meu(self.tv.selection()[0]))

            # coluna 3: vídeo e controles
            self.col3 = tk.Frame(self.corpo, bg=BG)
            self.col3.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(4, 8), pady=8)
            self.info = tk.Label(self.col3, text="Escolha um canal (clique duplo)", bg=BG, fg=FG,
                                 font=FONT_H, anchor="w")
            self.info.pack(fill=tk.X)
            self.lbl_agora = tk.Label(self.col3, text="", bg=BG, fg=KIDS, font=("Segoe UI", 9), anchor="w",
                                      justify="left", wraplength=700)
            self.lbl_agora.pack(fill=tk.X)
            self.video = tk.Frame(self.col3, bg="black", cursor="hand2")
            self.video.pack(fill=tk.BOTH, expand=True, pady=(4, 6))
            self.msg_video = tk.Label(self.video, text="", bg="black", fg=FG2, font=("Segoe UI", 13))
            self.msg_video.place(relx=0.5, rely=0.5, anchor="center")
            self.video.bind("<Double-1>", lambda e: self.tela_cheia())
            self.ctrl = tk.Frame(self.col3, bg=BG)
            self.ctrl.pack(fill=tk.X)
            self._btn(self.ctrl, "⏮", lambda: self.pular(-1), font=("Segoe UI", 12)).pack(side=tk.LEFT)
            self.b_play = self._btn(self.ctrl, "⏹", self.parar_ou_tocar, font=("Segoe UI", 12))
            self.b_play.pack(side=tk.LEFT, padx=4)
            self._btn(self.ctrl, "⏭", lambda: self.pular(1), font=("Segoe UI", 12)).pack(side=tk.LEFT)
            self.b_mudo = self._btn(self.ctrl, "🔊", self.mudo, font=("Segoe UI", 12))
            self.b_mudo.pack(side=tk.LEFT, padx=(14, 2))
            self.vol = tk.Scale(self.ctrl, from_=0, to=100, orient="horizontal", showvalue=False, length=130,
                                bg=BG, fg=FG, troughcolor=BG2, highlightthickness=0, sliderrelief=tk.FLAT,
                                command=self._volume)
            self.vol.set(self.est.d["volume"])
            self.vol.pack(side=tk.LEFT)
            self.b_fav = self._btn(self.ctrl, "☆ Favoritar", self.favoritar)
            self.b_fav.pack(side=tk.LEFT, padx=(14, 4))
            self._btn(self.ctrl, "⛶ Tela cheia", self.tela_cheia).pack(side=tk.LEFT)
            self.lbl_trans = tk.Label(self.ctrl, text="", bg=BG, fg=FG2, font=("Segoe UI", 9))
            self.lbl_trans.pack(side=tk.RIGHT)

            for seq, fn in (("<F11>", lambda e: self.tela_cheia()), ("<Escape>", lambda e: self.sair_tela_cheia()),
                            ("<Prior>", lambda e: self.pular(-1)), ("<Next>", lambda e: self.pular(1)),
                            ("<Control-m>", lambda e: self.mudo())):
                self.bind(seq, fn)
            self.b_add.config(state=tk.DISABLED if self.v_criancas.get() else tk.NORMAL)
            self.update_idletasks()
            self.player.set_hwnd(self.video.winfo_id())
            self.player.video_set_mouse_input(False)
            self.player.video_set_key_input(False)

        def _status(self, txt, cor=FG2):
            self.status.config(text=txt, fg=cor)

        # ---------- lista ----------
        def _carregar_lista(self, forcar=False):
            self._status("Baixando a lista de canais…" if forcar or not ARQ_LISTA.exists() else "Carregando canais…")

            def tarefa():
                try:
                    canais, aviso = carregar_tudo(self.pluto, forcar)
                    self.fila.put(("lista", canais))
                    if aviso:
                        self.fila.put(("status", (aviso, AVISO)))
                except Exception as e:
                    if not self.base:          # sem catálogo: ao menos "Meus canais" (antena, rede local) aparecem
                        self.fila.put(("lista", []))
                    self.fila.put(("status", (f"Não consegui baixar a lista de canais: {e}", ERRO)))
            threading.Thread(target=tarefa, daemon=True).start()

        def _receber_lista(self, canais):
            self.base = canais
            self._atualizar_canais()
            n = sum(len(c.transmissoes) for c in self.canais)
            self._status(f"{len(self.canais)} canais ({n} transmissões). Dica: “🩺 Verificar canais” "
                         f"mostra quais estão no ar agora; “➕ Adicionar canal” inclui os seus.", FG2)
            ult = self.est.d.get("ultimo")
            if ult and not self.atual:
                c = next((c for c in self.canais if c.chave == ult), None)
                if c and (not self.v_criancas.get() or c.infantil):
                    self._selecionar(c)

        def _atualizar_canais(self):
            self.canais = sorted(self.base + [canal_meu(d) for d in ler_meus()], key=lambda c: norm(c.nome))
            self._montar_categorias()
            self._filtrar()

        def _contagem(self, nome):
            return sum(1 for c in self.canais if self._na_categoria(c, nome))

        def _na_categoria(self, c, nome):
            if nome == "Todos":
                return True
            if nome == "⭐ Favoritos":
                return c.chave in self.est.d["favoritos"]
            if nome == INFANTIL:
                return c.infantil
            return nome in c.categorias

        def _montar_categorias(self):
            sel = self._categoria()
            self.lb_cat.delete(0, tk.END)
            if self.v_criancas.get():
                nomes = [INFANTIL, "⭐ Favoritos"]
            else:
                outras = sorted({k for c in self.canais for k in c.categorias} - {INFANTIL, MEUS}, key=norm)
                meus = [MEUS] if any(c.chave.startswith("meu.") for c in self.canais) else []
                nomes = ["Todos", "⭐ Favoritos", INFANTIL] + meus + outras
            self.nomes_cat = nomes
            for n in nomes:
                rot = f"🧸 {n}" if n == INFANTIL else (f"📌 {n}" if n == MEUS else n)
                self.lb_cat.insert(tk.END, f"{rot}  ({self._contagem(n)})")
                if n == INFANTIL:
                    self.lb_cat.itemconfig(tk.END, fg=KIDS)
            i = nomes.index(sel) if sel in nomes else 0
            self.lb_cat.selection_set(i)
            self.lb_cat.see(i)

        def _categoria(self):
            s = self.lb_cat.curselection() if hasattr(self, "nomes_cat") else ()
            return self.nomes_cat[s[0]] if s else ("Infantil" if self.v_criancas.get() else "Todos")

        def _status_canal(self, c):
            res = [self.est.no_ar(t.id_teste) for t in c.transmissoes]
            if any(r is True for r in res):
                return True
            if res and all(r is False for r in res):
                return False
            return None

        def _filtrar(self):
            if not hasattr(self, "nomes_cat"):
                return
            cat, termo = self._categoria(), norm(self.busca.get().strip())
            vis = []
            for c in self.canais:
                if self.v_criancas.get() and not c.infantil:
                    continue
                if not self._na_categoria(c, cat):
                    continue
                if termo and termo not in norm(c.nome):
                    continue
                if self.v_esconder.get() and self._status_canal(c) is False:
                    continue
                vis.append(c)
            self.visiveis = vis
            self.tv.delete(*self.tv.get_children())
            for c in vis:
                st = self._status_canal(c)
                marca = "●" if st else ("○" if st is False else "")
                tags = (["infantil"] if c.infantil else []) + (["fora"] if st is False else [])
                fav = "⭐ " if c.chave in self.est.d["favoritos"] else ""
                self.tv.insert("", tk.END, iid=c.chave, text=f" {fav}{c.nome}", values=(c.fonte, marca),
                               tags=tags, image=self.icones.get(c.logo, ""))
            self.lbl_lista.config(text=f"Canais — {cat} ({len(vis)})")
            if self.atual and self.atual.chave in self.tv.get_children():
                self.tv.selection_set(self.atual.chave)
                self.tv.see(self.atual.chave)
            self.after(50, self._carregar_logos_visiveis)

        def _opcoes(self):
            self.est.d["modo_criancas"] = self.v_criancas.get()
            self.est.d["esconder_fora"] = self.v_esconder.get()
            self.est.salvar()
            self.b_add.config(state=tk.DISABLED if self.v_criancas.get() else tk.NORMAL)
            self._montar_categorias()
            self._filtrar()
            if self.v_criancas.get() and self.atual and not self.atual.infantil:
                self.parar()

        # ---------- logos ----------
        def _carregar_logos_visiveis(self):
            if Image is None:
                return
            pend = [c for c in self.visiveis[:400] if c.logo and c.logo not in self.icones
                    and c.logo not in self.logo_pedidos]
            if not pend:
                return
            for c in pend:
                self.logo_pedidos.add(c.logo)

            def tarefa(lista):
                DIR_LOGOS.mkdir(parents=True, exist_ok=True)

                def um(url):
                    arq = DIR_LOGOS / (re.sub(r"[^\w]", "_", url)[-120:] + ".png")
                    try:
                        if not arq.exists():
                            req = urllib.request.Request(url, headers={"User-Agent": UA})
                            with urllib.request.urlopen(req, timeout=8) as r:
                                dados = r.read(3_000_000)
                            from io import BytesIO
                            im = Image.open(BytesIO(dados)).convert("RGBA")
                            im.thumbnail((40, 24))
                            fundo = Image.new("RGBA", (40, 24), (0, 0, 0, 0))
                            fundo.paste(im, ((40 - im.width) // 2, (24 - im.height) // 2), im)
                            fundo.save(arq)
                        self.fila.put(("logo", (url, str(arq))))
                    except Exception:
                        pass
                with ThreadPoolExecutor(8) as ex:
                    list(ex.map(um, lista))
            threading.Thread(target=tarefa, args=([c.logo for c in pend],), daemon=True).start()

        def _receber_logo(self, url, arq):
            try:
                self.icones[url] = ImageTk.PhotoImage(Image.open(arq))
            except Exception:
                return
            for c in self.visiveis:
                if c.logo == url and self.tv.exists(c.chave):
                    self.tv.item(c.chave, image=self.icones[url])

        # ---------- reprodução ----------
        def _selecionar(self, c):
            if self.tv.exists(c.chave):
                self.tv.selection_set(c.chave)
                self.tv.see(c.chave)
            self.tocar(c)

        def tocar_selecionado(self):
            sel = self.tv.selection()
            c = next((c for c in self.visiveis if sel and c.chave == sel[0]), None)
            if c:
                self.tocar(c)

        def tocar(self, c, idx=0):
            if self.v_criancas.get() and not c.infantil:
                return
            self.atual, self.idx_trans = c, idx
            t = c.transmissoes[idx]
            try:
                url = self.pluto.url(t.pluto_id) if t.pluto_id else t.url
            except Exception as e:
                self._status(f"Pluto TV indisponível agora: {e}", ERRO)
                return
            m = self.inst.media_new(url)
            m.add_option(f":http-user-agent={t.user_agent or UA}")
            if t.referrer:
                m.add_option(f":http-referrer={t.referrer}")
            if t.programa:
                m.add_option(f":program={t.programa}")
            self.player.set_media(m)
            self.player.play()
            self.t_inicio = time.time()
            self.est.d["ultimo"] = c.chave
            self.est.salvar()
            extra = " · pode estar fora do horário (não é 24 h)" if t.nao_24h else ""
            self.info.config(text=f"{'🧸 ' if c.infantil else ''}{c.nome}")
            self.lbl_agora.config(text=c.resumo[:160] if c.resumo else "")
            if t.pluto_id:
                self._buscar_agora(c, t.pluto_id)
            self.lbl_trans.config(text=f"{t.fonte}{' · ' + t.qualidade if t.qualidade else ''} · "
                                       f"transmissão {idx + 1}/{len(c.transmissoes)}{extra}")
            self.msg_video.config(text="Carregando…")
            self.msg_video.place(relx=0.5, rely=0.5, anchor="center")
            self.b_play.config(text="⏹")
            self.b_fav.config(text="★ Favorito" if c.chave in self.est.d["favoritos"] else "☆ Favoritar")
            self._status(f"Abrindo {c.nome}…")

        def _buscar_agora(self, c, pid):
            def tarefa():
                try:
                    prog = self.pluto.agora(pid)
                except Exception:
                    return
                self.fila.put(("agora", (c.chave, prog)))
            threading.Thread(target=tarefa, daemon=True).start()

        def _mostrar_agora(self, chave, prog):
            if not self.atual or self.atual.chave != chave or not prog:
                return
            from datetime import datetime

            def hora(iso):
                try:
                    return datetime.fromisoformat(iso.replace("Z", "+00:00")).astimezone().strftime("%Hh%M")
                except Exception:
                    return ""
            txt = f"▶ Agora: {prog[0][2]} (até {hora(prog[0][1])})"
            if len(prog) > 1:
                txt += f"   ·   Depois: {prog[1][2]}"
            self.lbl_agora.config(text=txt)

        def _falhou(self):
            c = self.atual
            t = c.transmissoes[self.idx_trans]
            if t.pluto_id and not self.pluto_refeito:
                self.pluto_refeito = True
                self._status(f"{c.nome}: renovando a sessão da Pluto TV…", AVISO)
                try:
                    self.pluto.sessao(forcar=True)
                    return self.tocar(c, self.idx_trans)
                except Exception:
                    pass
            self.est.d["testes"][t.id_teste] = [False, time.time()]
            if self.idx_trans + 1 < len(c.transmissoes):
                self._status(f"{c.nome}: transmissão {self.idx_trans + 1} não abriu, tentando a próxima…", AVISO)
                self.tocar(c, self.idx_trans + 1)
            else:
                self.player.stop()
                if t.url.startswith("isdb-t://"):
                    dica = ("Não sintonizou. Confira se o sintonizador USB de TV digital está ligado\n"
                            "e se o canal físico/frequência está certo (não é o número 5.1, 7.1 da TV).")
                elif c.chave.startswith("meu."):
                    dica = "O endereço não respondeu. Confira o link (botão direito → Editar)."
                else:
                    dica = "Tente outro canal."
                self.msg_video.config(text=f"{c.nome} está fora do ar agora.\n{dica}")
                self.msg_video.place(relx=0.5, rely=0.5, anchor="center")
                self._status(f"{c.nome} não respondeu em nenhuma das {len(c.transmissoes)} transmissão(ões).", ERRO)
                self.est.salvar()
                self._filtrar()

        def _vigiar(self):
            if self.atual is not None and self.b_play.cget("text") == "⏹":
                s = self.player.get_state()
                if s == vlc.State.Playing:
                    if self.msg_video.winfo_ismapped():
                        self.msg_video.place_forget()
                        chave = self.atual.transmissoes[self.idx_trans].id_teste
                        self.pluto_refeito = False
                        if self.est.no_ar(chave) is not True:
                            self.est.d["testes"][chave] = [True, time.time()]
                            self.est.salvar()
                        self._status(f"No ar: {self.atual.nome}", OK)
                elif s in (vlc.State.Error, vlc.State.Ended) or \
                        (s in (vlc.State.Opening, vlc.State.Buffering, vlc.State.NothingSpecial)
                         and time.time() - self.t_inicio > 20):
                    self._falhou()
            self.after(500, self._vigiar)

        def parar(self):
            self.player.stop()
            self.b_play.config(text="▶")
            self.msg_video.config(text="Parado")
            self.msg_video.place(relx=0.5, rely=0.5, anchor="center")

        def parar_ou_tocar(self):
            if self.b_play.cget("text") == "⏹":
                self.parar()
            elif self.atual:
                self.tocar(self.atual, self.idx_trans)

        def pular(self, passo):
            if not self.visiveis:
                return
            i = next((k for k, c in enumerate(self.visiveis) if self.atual and c.chave == self.atual.chave), -1)
            self._selecionar(self.visiveis[(i + passo) % len(self.visiveis)])

        def _volume(self, v):
            self.player.audio_set_volume(int(float(v)))
            self.est.d["volume"] = int(float(v))

        def mudo(self):
            m = not self.player.audio_get_mute()
            self.player.audio_set_mute(m)
            self.b_mudo.config(text="🔇" if m else "🔊")

        def favoritar(self):
            if not self.atual:
                return
            favs = self.est.d["favoritos"]
            if self.atual.chave in favs:
                favs.remove(self.atual.chave)
            else:
                favs.append(self.atual.chave)
            self.est.salvar()
            self.b_fav.config(text="★ Favorito" if self.atual.chave in favs else "☆ Favoritar")
            self._montar_categorias()
            self._filtrar()

        def tela_cheia(self):
            if self.cheia:
                return self.sair_tela_cheia()
            self.cheia = True
            for w in (self.hdr, self.status, self.col1, self.col2, self.ctrl, self.info, self.lbl_agora):
                w.pack_forget()
            self.col3.pack_configure(padx=0, pady=0)
            self.video.pack_configure(pady=0)
            self.attributes("-fullscreen", True)

        def sair_tela_cheia(self):
            if not self.cheia:
                return
            self.cheia = False
            self.attributes("-fullscreen", False)
            self.col3.pack_forget()
            self.video.pack_forget()
            self.hdr.pack(fill=tk.X, before=self.corpo)
            self.status.pack(fill=tk.X, side=tk.BOTTOM)
            self.col1.pack(side=tk.LEFT, fill=tk.Y, padx=(8, 4), pady=8)
            self.col2.pack(side=tk.LEFT, fill=tk.Y, padx=4, pady=8)
            self.col3.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(4, 8), pady=8)
            self.info.pack(fill=tk.X)
            self.lbl_agora.pack(fill=tk.X)
            self.video.pack(fill=tk.BOTH, expand=True, pady=(4, 6))
            self.ctrl.pack(fill=tk.X)

        # ---------- meus canais ----------
        def _menu_canal(self, ev):
            chave = self.tv.identify_row(ev.y)
            if not chave:
                return
            self.tv.selection_set(chave)
            menu = tk.Menu(self, tearoff=0, bg=BG2, fg=FG, activebackground=ACCENT, activeforeground="white")
            menu.add_command(label="▶  Assistir", command=self.tocar_selecionado)
            if self.v_criancas.get():
                pass                                    # modo crianças: só assistir
            elif chave.startswith("meu."):
                d = next((d for d in ler_meus() if f"meu.{d['id']}" == chave), None)
                menu.add_command(label="✏️  Editar…", command=lambda: self.dialogo_canal(d))
                menu.add_command(label="🗑  Remover", command=lambda: self.remover_meu(chave))
            else:
                menu.add_command(label="➕  Adicionar canal…", command=self.dialogo_canal)
            menu.tk_popup(ev.x_root, ev.y_root)

        def remover_meu(self, chave):
            d = next((d for d in ler_meus() if f"meu.{d['id']}" == chave), None)
            if not d or not messagebox.askyesno("Remover canal", f"Remover “{d['nome']}” dos seus canais?",
                                                parent=self):
                return
            salvar_meus([x for x in ler_meus() if x["id"] != d["id"]])
            if chave in self.est.d["favoritos"]:
                self.est.d["favoritos"].remove(chave)
            if self.est.d.get("ultimo") == chave:
                self.est.d["ultimo"] = ""
            self.est.d["testes"].pop(d["url"], None)
            self.est.salvar()
            if self.atual and self.atual.chave == chave:
                self.parar()
                self.atual = None
                self.info.config(text="Escolha um canal (clique duplo)")
                self.lbl_agora.config(text="")
                self.lbl_trans.config(text="")
            self._atualizar_canais()
            self._status(f"“{d['nome']}” removido.", FG2)

        def dialogo_canal(self, dados=None):
            """Adiciona (ou edita) um canal próprio: link/endereço de rede ou antena digital."""
            dados = dict(dados or {})
            w = tk.Toplevel(self)
            w.title("Editar canal" if dados else "Adicionar canal")
            w.configure(bg=BG, padx=18, pady=14)
            w.resizable(False, False)
            w.transient(self)
            if _recurso("canais_abertos.ico").exists():
                try:
                    w.iconbitmap(str(_recurso("canais_abertos.ico")))
                except Exception:
                    pass

            tipo = tk.StringVar(value=dados.get("tipo", "link"))
            ant = tipo.get() == "antena"
            v_nome = tk.StringVar(value=dados.get("nome", ""))
            v_end = tk.StringVar(value="" if ant else dados.get("entrada", ""))
            v_freq = tk.StringVar(value=dados.get("entrada", "") if ant else "")
            v_prog = tk.StringVar(value=dados.get("programa", ""))
            v_ua = tk.StringVar(value=dados.get("user_agent", ""))
            v_ref = tk.StringVar(value=dados.get("referrer", ""))
            v_cat = tk.StringVar(value=dados.get("categoria") or MEUS)
            v_inf = tk.BooleanVar(value=bool(dados.get("infantil")))

            def rotulo(pai, txt, **kw):
                return tk.Label(pai, text=txt, bg=BG, fg=kw.pop("fg", FG2), font=kw.pop("font", FONT),
                                anchor="w", justify="left", **kw)

            def campo(pai, var, largura=52):
                return tk.Entry(pai, textvariable=var, bg=BG2, fg=FG, insertbackground=FG, relief=tk.FLAT,
                                font=FONT, width=largura)

            rotulo(w, "Como o canal chega até você?", fg=FG, font=FONT_B).pack(fill=tk.X)
            fr_tipo = tk.Frame(w, bg=BG)
            fr_tipo.pack(fill=tk.X, pady=(4, 10))
            for txt, val in (("🔗 Link ou endereço de rede", "link"), ("📡 Antena digital (frequência)", "antena")):
                tk.Radiobutton(fr_tipo, text=txt, value=val, variable=tipo, command=lambda: trocar(),
                               bg=BG, fg=FG, selectcolor=BG2, activebackground=BG, activeforeground=FG,
                               font=FONT).pack(side=tk.LEFT, padx=(0, 16))

            rotulo(w, "Nome do canal").pack(fill=tk.X)
            e_nome = campo(w, v_nome)
            e_nome.pack(fill=tk.X, ipady=3, pady=(2, 10))

            fr_link = tk.Frame(w, bg=BG)
            rotulo(fr_link, "Link ou endereço").pack(fill=tk.X)
            e_end = campo(fr_link, v_end)
            e_end.pack(fill=tk.X, ipady=3, pady=(2, 2))
            rotulo(fr_link, "Ex.: https://site.com/aovivo.m3u8 · rtmp://… · rtsp://…\n"
                            "      192.168.0.20:8080/stream (rede local) · udp://@239.0.0.1:1234 (operadora)",
                   font=("Segoe UI", 8)).pack(fill=tk.X)
            rotulo(fr_link, "Opcional — só se o site exigir:", font=("Segoe UI", 8)).pack(fill=tk.X, pady=(8, 0))
            fr_opc = tk.Frame(fr_link, bg=BG)
            fr_opc.pack(fill=tk.X)
            rotulo(fr_opc, "User-Agent", font=("Segoe UI", 8)).grid(row=0, column=0, sticky="w")
            campo(fr_opc, v_ua, 40).grid(row=0, column=1, sticky="we", padx=(6, 0), pady=1)
            rotulo(fr_opc, "Referer", font=("Segoe UI", 8)).grid(row=1, column=0, sticky="w")
            campo(fr_opc, v_ref, 40).grid(row=1, column=1, sticky="we", padx=(6, 0), pady=1)
            fr_opc.columnconfigure(1, weight=1)

            fr_ant = tk.Frame(w, bg=BG)
            rotulo(fr_ant, "Canal físico ou frequência").pack(fill=tk.X)
            e_freq = campo(fr_ant, v_freq, 20)
            e_freq.pack(anchor="w", ipady=3, pady=(2, 2))
            rotulo(fr_ant, "Ex.: 28 (canal físico) ou 557,142 (MHz). O canal físico não é o número da TV\n"
                           "(5.1, 7.1…): veja em “Ver informação do canal” na TV ou no site da Anatel.",
                   font=("Segoe UI", 8)).pack(fill=tk.X)
            rotulo(fr_ant, "Programa / serviço (opcional)").pack(fill=tk.X, pady=(8, 0))
            campo(fr_ant, v_prog, 8).pack(anchor="w", ipady=3, pady=(2, 2))
            rotulo(fr_ant, "Número do serviço quando a mesma frequência traz mais de um canal.\n"
                           "Precisa de um sintonizador USB de TV digital (ISDB-T) ligado ao computador.",
                   font=("Segoe UI", 8), fg=AVISO).pack(fill=tk.X)

            fr_fim = tk.Frame(w, bg=BG)
            rotulo(fr_fim, "Categoria").pack(fill=tk.X, pady=(10, 0))
            cats = [MEUS] + sorted({k for c in self.base for k in c.categorias} - {INFANTIL}, key=norm)
            ttk.Combobox(fr_fim, textvariable=v_cat, values=cats, font=FONT).pack(fill=tk.X, pady=(2, 6))
            tk.Checkbutton(fr_fim, text="🧸 É canal infantil (aparece no modo crianças)", variable=v_inf,
                           bg=BG, fg=FG, selectcolor=BG2, activebackground=BG, activeforeground=FG,
                           font=FONT, anchor="w").pack(fill=tk.X)
            rotulo(fr_fim, "Use só transmissões que você tem direito de assistir (emissora, operadora, sua antena).",
                   font=("Segoe UI", 8)).pack(fill=tk.X, pady=(8, 0))
            fr_bt = tk.Frame(fr_fim, bg=BG)
            fr_bt.pack(fill=tk.X, pady=(12, 0))
            self._btn(fr_bt, "Cancelar", w.destroy).pack(side=tk.RIGHT)
            self._btn(fr_bt, "Salvar e assistir", lambda: salvar(), bg=ACCENT, fg="white",
                      font=FONT_B).pack(side=tk.RIGHT, padx=(0, 8))

            def trocar():
                for f in (fr_link, fr_ant, fr_fim):
                    f.pack_forget()
                (fr_ant if tipo.get() == "antena" else fr_link).pack(fill=tk.X)
                fr_fim.pack(fill=tk.X)
                (e_freq if tipo.get() == "antena" else e_end).focus_set()

            def salvar():
                try:
                    if tipo.get() == "antena":
                        entrada, hz = v_freq.get().strip(), frequencia_hz(v_freq.get())
                        url = f"isdb-t://frequency={hz}:bandwidth=6"
                        prog = v_prog.get().strip()
                        if prog and not prog.isdigit():
                            raise ValueError("O programa/serviço é um número (ex.: 1). Deixe em branco se não souber.")
                    else:
                        entrada, url, prog = v_end.get().strip(), normalizar_endereco(v_end.get()), ""
                except ValueError as e:
                    messagebox.showwarning(w.title(), str(e), parent=w)
                    return
                nome = v_nome.get().strip() or (f"Canal {entrada}" if tipo.get() == "antena"
                                                else urlparse(url).hostname or entrada)
                import uuid
                d = {"id": dados.get("id") or uuid.uuid4().hex[:10], "nome": nome, "tipo": tipo.get(),
                     "entrada": entrada, "url": url, "programa": prog,
                     "categoria": v_cat.get().strip() or MEUS, "infantil": v_inf.get(),
                     "user_agent": v_ua.get().strip() if tipo.get() == "link" else "",
                     "referrer": v_ref.get().strip() if tipo.get() == "link" else ""}
                lista = [x for x in ler_meus() if x["id"] != d["id"]]
                salvar_meus(lista + [d])
                self.est.d["testes"].pop(url, None)        # endereço novo: esquece testes antigos
                w.destroy()
                self._atualizar_canais()
                c = next(c for c in self.canais if c.chave == f"meu.{d['id']}")
                if not self.tv.exists(c.chave):            # categoria/busca atual esconde o canal novo
                    i = self.nomes_cat.index(MEUS) if MEUS in self.nomes_cat else 0
                    self.lb_cat.selection_clear(0, tk.END)
                    self.lb_cat.selection_set(i)
                    self.lb_cat.see(i)
                    self.busca.set("")
                    self._filtrar()
                self._status(f"“{nome}” salvo em {MEUS}.", OK)
                self._selecionar(c)

            trocar()
            w.bind("<Return>", lambda e: salvar())
            w.bind("<Escape>", lambda e: w.destroy())
            w.update_idletasks()
            x = self.winfo_rootx() + (self.winfo_width() - w.winfo_reqwidth()) // 2
            y = self.winfo_rooty() + max(0, (self.winfo_height() - w.winfo_reqheight()) // 3)
            w.geometry(f"+{x}+{y}")
            w.grab_set()
            e_nome.focus_set()

        # ---------- verificação ----------
        def verificar(self):
            alvo = [c for c in self.canais if not self.v_criancas.get() or c.infantil]
            trans = [t for c in alvo for t in c.transmissoes]
            if not trans:
                return
            self._status(f"Verificando {len(trans)} transmissões… (dá para assistir enquanto isso)")

            def tarefa():
                feitos = 0
                with ThreadPoolExecutor(24) as ex:
                    for t, ok in zip(trans, ex.map(lambda t: testar_transmissao(t, self.pluto), trans)):
                        if ok is not None:          # antena/udp/rtsp só dá para saber abrindo o vídeo
                            self.est.d["testes"][t.id_teste] = [ok, time.time()]
                        feitos += 1
                        if feitos % 25 == 0:
                            self.fila.put(("status", (f"Verificando… {feitos}/{len(trans)}", FG2)))
                no_ar = sum(1 for c in alvo if any(self.est.d["testes"].get(t.id_teste, [False])[0] for t in c.transmissoes))
                self.fila.put(("verificado", (no_ar, len(alvo))))
            threading.Thread(target=tarefa, daemon=True).start()

        # ---------- fila de mensagens das threads ----------
        def _processar_fila(self):
            try:
                while True:
                    tipo, dado = self.fila.get_nowait()
                    if tipo == "lista":
                        self._receber_lista(dado)
                    elif tipo == "status":
                        self._status(*dado)
                    elif tipo == "logo":
                        self._receber_logo(*dado)
                    elif tipo == "agora":
                        self._mostrar_agora(*dado)
                    elif tipo == "verificado":
                        self.est.salvar()
                        self._filtrar()
                        self._status(f"Verificação concluída: {dado[0]} de {dado[1]} canais no ar agora "
                                     f"(● no ar · ○ fora do ar).", OK)
            except queue.Empty:
                pass
            self.after(150, self._processar_fila)

        def sair(self):
            try:
                self.est.d["geometria"] = self.geometry() if not self.cheia else self.est.d.get("geometria", "")
                self.est.salvar()
                self.player.stop()
            finally:
                self.destroy()

    App().mainloop()


def listar():
    sys.stdout.reconfigure(encoding="utf-8")
    motivos = []
    montar_canais(baixar_lista(), motivos)
    canais, aviso = carregar_tudo(Pluto(Estado().d["id_aparelho"]))
    if aviso:
        print("AVISO:", aviso)
    print(f"ENTRAM: {len(canais)} canais, {sum(len(c.transmissoes) for c in canais)} transmissões")
    from collections import Counter
    print("fontes:", Counter(t.fonte for c in canais for t in c.transmissoes).most_common())
    print("infantis:", ", ".join(c.nome for c in canais if c.infantil))
    print(f"\nSAEM: {len(motivos)} transmissões")
    print(Counter(m for _, m, _ in motivos).most_common())
    for nome, m, url in sorted(motivos)[:400]:
        print(f"  - {nome[:38]:<38} {m[:40]:<40} {url[:60]}")


if __name__ == "__main__":
    listar() if "--listar" in sys.argv else app()
