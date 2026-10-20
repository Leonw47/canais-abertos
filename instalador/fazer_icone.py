# Desenha o ícone do Canais Abertos (uma TV com antena) em várias resoluções.
import sys
from PIL import Image, ImageDraw

S = 1024
im = Image.new("RGBA", (S, S), (0, 0, 0, 0))
d = ImageDraw.Draw(im)
roxo, roxo_esc, branco = (124, 106, 247, 255), (74, 60, 190, 255), (255, 255, 255, 255)
d.rounded_rectangle((40, 40, S - 40, S - 40), radius=210, fill=roxo)
# antena
d.line((S * 0.40, S * 0.30, S * 0.30, S * 0.14), fill=branco, width=46)
d.line((S * 0.60, S * 0.30, S * 0.70, S * 0.14), fill=branco, width=46)
d.ellipse((S * 0.27 - 34, S * 0.13 - 34, S * 0.27 + 34, S * 0.13 + 34), fill=branco)
d.ellipse((S * 0.73 - 34, S * 0.13 - 34, S * 0.73 + 34, S * 0.13 + 34), fill=branco)
# corpo da TV e tela
d.rounded_rectangle((S * 0.14, S * 0.30, S * 0.86, S * 0.80), radius=70, fill=branco)
d.rounded_rectangle((S * 0.20, S * 0.36, S * 0.80, S * 0.74), radius=45, fill=roxo_esc)
# botão "play" na tela
d.polygon([(S * 0.44, S * 0.45), (S * 0.44, S * 0.65), (S * 0.61, S * 0.55)], fill=branco)
# pés
d.rounded_rectangle((S * 0.28, S * 0.80, S * 0.36, S * 0.86), radius=12, fill=branco)
d.rounded_rectangle((S * 0.64, S * 0.80, S * 0.72, S * 0.86), radius=12, fill=branco)
saida = sys.argv[1]
im.resize((256, 256), Image.LANCZOS).save(saida, sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
im.resize((256, 256), Image.LANCZOS).save(saida.replace(".ico", ".png"))
print("ok", saida)
