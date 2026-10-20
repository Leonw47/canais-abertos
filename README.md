# Canais Abertos

TV ao vivo em português para Windows, **só com fontes abertas e gratuitas** — incluindo canais infantis
(Turma da Mônica, Cocoricó, Bob Esponja…).

- **Pluto TV Brasil oficial** (canais gratuitos com anúncios), com sessão própria.
- **Lista pública do [iptv-org](https://github.com/iptv-org/iptv)** em português, filtrada: ficam emissoras
  públicas, educativas, regionais e religiosas transmitindo dos próprios servidores; saem retransmissões de TV
  paga (IPs soltos, domínios de retransmissão, marcas de TV por assinatura fora de plataformas gratuitas).
- O programa **não importa listas M3U inteiras** de propósito: listas com canais pagos são pirataria.
- **Meus canais:** dá para adicionar um canal próprio por link, endereço de rede ou frequência da antena
  digital (ISDB-T, com sintonizador USB). Esses não passam pelo filtro — a fonte é responsabilidade de quem adiciona.

## Instalar
Baixe `CanaisAbertos-Setup-<versão>.exe` em **Releases** e execute (instala só para o seu usuário, sem pedir
administrador). O instalador já traz o motor de vídeo: não precisa ter o VLC instalado. Se o Windows avisar que o
app não é assinado: **Mais informações → Executar assim mesmo**.

## Rodar pelo código
Requer Python 3 e o **VLC 64 bits** instalado.
```bash
pip install -r requirements.txt
python canais_abertos.py            # abre o programa
python canais_abertos.py --listar   # mostra no terminal o que entra e o que sai do filtro
```
Favoritos, testes e canais próprios ficam em `%APPDATA%\CanaisAbertos`.

## Gerar o instalador
Precisa do VLC 64 bits em `C:\Program Files\VideoLAN\VLC`, do PyInstaller e do NSIS 3 (o script procura o
`makensis.exe` no cache do electron-builder).
```bash
powershell -ExecutionPolicy Bypass -File instalador/gerar_instalador.ps1
```
Para uma versão nova, mude `VERSAO` em `instalador/canais_abertos.nsi`. O `.exe` sai em `instalador/`
(fora do git — vai como anexo do release). `"Canais Abertos.exe" --autoteste <arquivo.json>` valida o pacote.

Histórico de versões em [CHANGELOG.md](CHANGELOG.md).
