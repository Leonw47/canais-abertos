# Changelog

Versões no padrão [SemVer](https://semver.org/lang/pt-BR/): correções sobem o PATCH, recursos novos o MINOR.

## [1.2.0] — 2026-11-07
### Adicionado
- **🌎 Canais em inglês/espanhol:** desenhos, animes, filmes, séries, comédia e clássicos dos canais gratuitos
  oficiais de fora (Pluto TV de outros países, Samsung TV Plus, Plex e outras plataformas com anúncios) — ex.:
  Sonic TV, Pluto TV Anime, Crunchyroll, Anime x HIDIVE, One Piece, Naruto Shippuden, Yu-Gi-Oh!, Detective Conan,
  As Tartarugas Ninja, Mr. Bean Animado e as coleções de South Park. Cerca de 420 canais, com o idioma no nome
  ("· inglês", "· espanhol") e categorias próprias ("🌎 Desenhos e Animes (outros idiomas)"…); a opção
  "🌎 Canais em inglês/espanhol" mostra ou esconde todos. Versões repetidas do mesmo canal (vários países) viram
  uma só, de preferência a dos EUA ou da América Latina.
- Como na lista em português, só entram plataformas gratuitas oficiais: nas listas de fora, Cartoon Network,
  Adult Swim e outros canais pagos só aparecem como retransmissão pirata e ficam de fora.

## [1.1.0] — 2026-10-12
### Adicionado
- **➕ Adicionar canal:** canais próprios por link (HLS/HTTP), endereço de rede (IP vira `http://`, multicast vira
  `udp://@`) ou frequência da antena digital (ISDB-T: canal físico 7–69 ou MHz, com sintonizador USB). Ficam na
  categoria "📌 Meus canais", com Editar/Remover no botão direito, e não passam pelo filtro de legitimidade
  (a fonte é escolha de quem adiciona). Desativado no modo crianças.

## [1.0.0] — 2026-10-12
### Adicionado
- TV ao vivo em português só com fontes abertas: Pluto TV Brasil oficial (sessão própria, 179 canais, com
  anúncios) e a lista pública do iptv-org filtrada (emissoras públicas, educativas, regionais e religiosas nos
  próprios servidores); retransmissões de TV paga ficam de fora.
- Categorias, busca, favoritos, guia "Agora: …", verificação de quais canais estão no ar, modo crianças.
- Player embutido (motor do VLC) e instalador por usuário (PyInstaller + NSIS), sem precisar de VLC instalado.
