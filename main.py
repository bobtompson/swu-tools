import lib.swudb as swudb

import gspread
from oauth2client.service_account import ServiceAccountCredentials


def get_doc_sheet(sheet_name):
# Returns the specific sub sheet in the google spreadsheet
    # Define scope
    scope = [
        "https://spreadsheets.google.com/feeds",
        "https://www.googleapis.com/auth/drive",
    ]

    # Authenticate
    creds = ServiceAccountCredentials.from_json_keyfile_name("credentials.json", scope)
    client = gspread.authorize(creds)

    # Open the spreadsheet and select a worksheet
    spreadsheet = client.open("SWU Sets Inventory")
    return spreadsheet.worksheet(sheet_name)


def test_sheets():
# Testing for google sheet and api data
    # Define scope
    scope = [
        "https://spreadsheets.google.com/feeds",
        "https://www.googleapis.com/auth/drive",
    ]

    # Authenticate
    creds = ServiceAccountCredentials.from_json_keyfile_name("credentials.json", scope)
    client = gspread.authorize(creds)



    # Open the spreadsheet and select a worksheet
    spreadsheet = client.open("SWU Sets Inventory")
    # sheet = spreadsheet.sheet1  # Or use .worksheet("Sheet1")
    sheet = spreadsheet.worksheet("SOR")
    card_num = sheet.cell(12,1).value
    card_name = sheet.cell(12,2).value
    sheet.update_cell(11,2,'Hello for python')

    print(f"Card {card_num}: {card_name}")

def update_list_names(card_list):
    """Update the names and rarity columns in my inventory spreadsheet in google.
    Each Subsheet is a set name abbr.
    """
    set_df = swudb.get_swu_list(card_list.lower())

    if set_df is None:
        print(f"Failed to get card data for {card_list.upper()}, aborting update.")
        return

    sheet = get_doc_sheet(card_list.upper())
    card_count = int(sheet.cell(1, 8).value)
    db_count = len(set_df)

    print(f"Card count: {card_count} for {card_list.upper()}")
    print(f"DB returned: {db_count} cards for {card_list.upper()}")

    curr_num = 1
    card_names = []
    card_rarity = []
    for num in range(card_count):
        card_num = "{:03d}".format(curr_num) # 3 Digit format
        # print(f"Setting Card {card_num} for {num}")
        card_names.append(swudb.get_card_name(set_df, card_num))
        card_rarity.append(swudb.get_card_rarity(set_df, card_num))
        curr_num += 1

    column_data = [[val] for val in card_names]
    rarity_data = [[val] for val in card_rarity]
    sheet.update(column_data, f"B3:B{len(card_names) + 3}")
    sheet.update(rarity_data, f"D3:D{len(card_names) + 3}")


# Press the green button in the gutter to run the script.
if __name__ == '__main__':
    update_list_names("sec")

    # Already Run
    # update_list_names('lof')
    # update_list_names('sor')
    # update_list_names('shd')
    # update_list_names('twi')
    # update_list_names('jtl')





