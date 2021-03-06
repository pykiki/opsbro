import time

from opsbro.cli_display import DonutPrinter
from opsbro.log import cprint
from opsbro.characters import CHARACTERS

p = DonutPrinter()

cprint(CHARACTERS.dot_bar, color='green')
cprint(CHARACTERS.bar_fill * 20, color='green', end='')
cprint(CHARACTERS.bar_unfill * 10, color='grey')

donut = p.get_donut(33)
cprint(donut)

for i in range(0, 101):
    cprint('\033c')
    donut = p.get_donut(i)
    cprint(donut)
    time.sleep(0.1)
