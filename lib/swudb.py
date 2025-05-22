import requests
import pandas as pd

def get_swu_list(set_name):
# Hits API for a list of all cards in a set. JSON Returned from API and converted to Dataframe
    # Hard coding sets for now, can modularize later
    if set_name == 'sor':
        sor_url = 'https://api.swu-db.com/cards/sor'
        response = requests.get(sor_url)
    if set_name == 'shd':
        shd_url = 'https://api.swu-db.com/cards/shd'
        response = requests.get(shd_url)
    if set_name == 'twi':
        twi_url = 'https://api.swu-db.com/cards/twi'
        response = requests.get(twi_url)
    if set_name == 'jtl':
        jtl_url = 'https://api.swu-db.com/cards/jtl'
        response = requests.get(jtl_url)

    try:
        df = False
        if(response.status_code == 200):
            print(f"{set_name.upper()} Card List Retrieved")
            set_json = response.json()
            # print_json(data=set_json)
            df = pd.DataFrame(set_json['data'])
        return df

    except NameError:
        print("No valid set specified: sor, shd, twi, jtl")
        return False

def get_card_name(list_df, num):
# Returns the string of card name in a card list
    name = str(list_df[list_df['Number'] == num].iloc[0]['Name'])
    # print(f"Card {num}: {name}")
    return name

def get_card_rarity(list_df, num):
# Returns the string of card rarity in a card list
    rarity = str(list_df[list_df['Number'] == num].iloc[0]['Rarity'])
    # print(f"Card {num}: {name}")
    return rarity[:1]

def get_card(list_df, num):
    card = list_df[list_df['Number'] == num].iloc[0]
    print(card)
