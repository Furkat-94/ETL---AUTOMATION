import pandas as pd
from sqlalchemy import create_engine


def load_to_sql(df):
    engine = create_engine("sqlite:///baseql.db")
    df.to_sql("Loading", con=engine, if_exists="append", index=False)
    return df


def load_to_excel(df):
    df.to_excel("base_excel_formation_hd.xlsx")
    return df


def load_to_csv(df):
    df.to_csv("base_csv_formation_hd.csv")
    return df