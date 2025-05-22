import lib.swudb as swudb
from rich.console import Console
from rich.table import Table
import pandas as pd

if __name__ == '__main__':
    SORList = swudb.get_swu_list('sor')

    console = Console()
    # table = Table('SOR')
    # table.add_row(SORList.to_string(float_format=lambda _: '{:.4f}'.format(_)))
    # console.print(table)
    with pd.option_context('display.max_rows', None,
                        'display.max_columns', None,
                        'display.precision', 3,
                        ):
        print(SORList.head(10))