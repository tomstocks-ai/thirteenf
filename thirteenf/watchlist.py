"""Built-in institution watchlist: the ~100 largest 13F filers.

Ranked by latest reported 13F holdings value (13f.info manager pages,
mostly Q2 2026). Every CIK was verified against the 13f.info
autocomplete endpoint and/or the SEC EDGAR submissions API
(data.sec.gov) at build time.

Fields:
  value_b  latest 13F holdings value in $billions (approximate; 13F values
           for trading firms include options notional)
  ratings  True when the institution or a broker-dealer affiliate publishes
           sell-side analyst ratings/research — a conflict-of-interest flag
           when their 13F positioning moves around their own ratings.

Note: "the 100 biggest" by raw 13F value excludes iconic but concentrated
funds (Pershing Square, Icahn, Soros, Baupost, Third Point, Starboard,
Trian, Oaktree, Appaloosa, Duquesne, Lone Pine, Maverick, Whale Rock,
Altimeter...) whose 13Fs are small relative to their influence.
"""

from __future__ import annotations

from typing import TypedDict


class Institution(TypedDict):
    name: str
    cik: str  # 10-digit zero-padded
    category: str  # index | assetmgr | bank | quant | hedge | tiger | activist | pension | insurance | biotech
    value_b: float  # latest 13F holdings value, $billions
    ratings: bool  # publishes sell-side analyst ratings (conflict-of-interest flag)


WATCHLIST: list[Institution] = [
    # --- index ---
    {"name": "Vanguard Group", "cik": "0000102909", "category": "index", "value_b": 6900.0, "ratings": False},
    {"name": "BlackRock", "cik": "0001364742", "category": "index", "value_b": 4420.0, "ratings": False},
    {"name": "State Street", "cik": "0000093751", "category": "index", "value_b": 3370.0, "ratings": False},
    # --- assetmgr ---
    {"name": "FMR LLC", "cik": "0000315066", "category": "assetmgr", "value_b": 2300.0, "ratings": False},
    # --- bank ---
    {"name": "Morgan Stanley", "cik": "0000895421", "category": "bank", "value_b": 1890.0, "ratings": True},
    # --- index ---
    {"name": "Geode Capital Management", "cik": "0001214717", "category": "index", "value_b": 1880.0, "ratings": False},
    # --- bank ---
    {"name": "JPMorgan Chase", "cik": "0000019617", "category": "bank", "value_b": 1810.0, "ratings": True},
    {"name": "Bank of America Corp", "cik": "0000070858", "category": "bank", "value_b": 1550.0, "ratings": True},
    # --- quant ---
    {"name": "Susquehanna International Group", "cik": "0001446194", "category": "quant", "value_b": 1280.0, "ratings": False},
    # --- index ---
    {"name": "Invesco Ltd", "cik": "0000914208", "category": "index", "value_b": 1260.0, "ratings": False},
    # --- quant ---
    {"name": "Jane Street Group", "cik": "0001595888", "category": "quant", "value_b": 1210.0, "ratings": False},
    # --- bank ---
    {"name": "Goldman Sachs Group", "cik": "0000886982", "category": "bank", "value_b": 1150.0, "ratings": True},
    # --- pension ---
    {"name": "Norges Bank", "cik": "0001374170", "category": "pension", "value_b": 1000.0, "ratings": False},
    # --- assetmgr ---
    {"name": "T. Rowe Price Associates", "cik": "0000080255", "category": "assetmgr", "value_b": 999.0, "ratings": False},
    # --- hedge ---
    {"name": "Citadel Advisors", "cik": "0001423053", "category": "hedge", "value_b": 875.0, "ratings": False},
    # --- index ---
    {"name": "Northern Trust Corp", "cik": "0000073124", "category": "index", "value_b": 860.0, "ratings": False},
    # --- assetmgr ---
    {"name": "Capital World Investors", "cik": "0001422849", "category": "assetmgr", "value_b": 846.0, "ratings": False},
    # --- bank ---
    {"name": "UBS Group AG", "cik": "0001610520", "category": "bank", "value_b": 786.0, "ratings": True},
    # --- pension ---
    {"name": "California State Teachers Retirement System", "cik": "0001081019", "category": "pension", "value_b": 782.0, "ratings": False},
    # --- index ---
    {"name": "Charles Schwab Investment Management", "cik": "0000884546", "category": "index", "value_b": 751.0, "ratings": False},
    # --- assetmgr ---
    {"name": "Capital Research Global Investors", "cik": "0001422848", "category": "assetmgr", "value_b": 717.0, "ratings": False},
    # --- bank ---
    {"name": "Royal Bank of Canada", "cik": "0001000275", "category": "bank", "value_b": 672.0, "ratings": True},
    {"name": "Wells Fargo", "cik": "0000072971", "category": "bank", "value_b": 617.0, "ratings": True},
    # --- assetmgr ---
    {"name": "Bank of New York Mellon", "cik": "0001390777", "category": "assetmgr", "value_b": 609.0, "ratings": False},
    {"name": "Wellington Management", "cik": "0000902219", "category": "assetmgr", "value_b": 580.0, "ratings": False},
    # --- index ---
    {"name": "Dimensional Fund Advisors", "cik": "0000354204", "category": "index", "value_b": 552.0, "ratings": False},
    # --- bank ---
    {"name": "Barclays", "cik": "0000312069", "category": "bank", "value_b": 521.0, "ratings": True},
    # --- assetmgr ---
    {"name": "Ameriprise Financial", "cik": "0000820027", "category": "assetmgr", "value_b": 495.0, "ratings": False},
    {"name": "Capital International Investors", "cik": "0001562230", "category": "assetmgr", "value_b": 484.0, "ratings": False},
    {"name": "Franklin Resources", "cik": "0000038777", "category": "assetmgr", "value_b": 462.0, "ratings": False},
    # --- bank ---
    {"name": "Raymond James Financial", "cik": "0000720005", "category": "bank", "value_b": 369.0, "ratings": True},
    {"name": "Deutsche Bank", "cik": "0000948046", "category": "bank", "value_b": 344.0, "ratings": True},
    # --- assetmgr ---
    {"name": "Massachusetts Financial Services", "cik": "0000912938", "category": "assetmgr", "value_b": 315.0, "ratings": False},
    # --- bank ---
    {"name": "Bank of Montreal", "cik": "0000927971", "category": "bank", "value_b": 304.0, "ratings": True},
    {"name": "Citigroup", "cik": "0000831001", "category": "bank", "value_b": 303.0, "ratings": True},
    # --- assetmgr ---
    {"name": "AllianceBernstein", "cik": "0001109448", "category": "assetmgr", "value_b": 302.0, "ratings": False},
    # --- insurance ---
    {"name": "Berkshire Hathaway", "cik": "0001067983", "category": "insurance", "value_b": 299.0, "ratings": False},
    # --- bank ---
    {"name": "BNP Paribas", "cik": "0001166588", "category": "bank", "value_b": 289.0, "ratings": True},
    # --- quant ---
    {"name": "AQR Capital Management", "cik": "0001167557", "category": "quant", "value_b": 287.0, "ratings": False},
    # --- hedge ---
    {"name": "Millennium Management", "cik": "0001273087", "category": "hedge", "value_b": 276.0, "ratings": False},
    # --- bank ---
    {"name": "HSBC Holdings", "cik": "0000873630", "category": "bank", "value_b": 239.0, "ratings": True},
    # --- quant ---
    {"name": "D.E. Shaw", "cik": "0001009207", "category": "quant", "value_b": 210.0, "ratings": False},
    # --- assetmgr ---
    {"name": "Principal Financial Group", "cik": "0001126328", "category": "assetmgr", "value_b": 203.64, "ratings": False},
    {"name": "Dodge & Cox", "cik": "0000200217", "category": "assetmgr", "value_b": 191.0, "ratings": False},
    # --- pension ---
    {"name": "Swiss National Bank", "cik": "0001582202", "category": "pension", "value_b": 191.0, "ratings": False},
    {"name": "Canada Pension Plan Investment Board", "cik": "0001283718", "category": "pension", "value_b": 180.78, "ratings": False},
    {"name": "California Public Employees Retirement System", "cik": "0000919079", "category": "pension", "value_b": 177.0, "ratings": False},
    # --- bank ---
    {"name": "Sumitomo Mitsui Trust", "cik": "0001475365", "category": "bank", "value_b": 175.0, "ratings": False},
    # --- index ---
    {"name": "First Trust Advisors", "cik": "0001125816", "category": "index", "value_b": 170.0, "ratings": False},
    # --- assetmgr ---
    {"name": "Jennison Associates", "cik": "0000053417", "category": "assetmgr", "value_b": 167.0, "ratings": False},
    # --- index ---
    {"name": "Van Eck Associates", "cik": "0000869178", "category": "index", "value_b": 164.0, "ratings": False},
    # --- assetmgr ---
    {"name": "Neuberger Berman", "cik": "0001465109", "category": "assetmgr", "value_b": 150.0, "ratings": False},
    # --- quant ---
    {"name": "Two Sigma Investments", "cik": "0001179392", "category": "quant", "value_b": 138.0, "ratings": False},
    # --- hedge ---
    {"name": "Marshall Wace", "cik": "0001318757", "category": "hedge", "value_b": 127.0, "ratings": False},
    # --- bank ---
    {"name": "Stifel Financial", "cik": "0000720672", "category": "bank", "value_b": 120.0, "ratings": True},
    # --- insurance ---
    {"name": "Prudential Financial", "cik": "0001137774", "category": "insurance", "value_b": 91.8, "ratings": False},
    # --- hedge ---
    {"name": "Point72 Asset Management", "cik": "0001603466", "category": "hedge", "value_b": 90.7, "ratings": False},
    # --- bank ---
    {"name": "Toronto-Dominion Bank", "cik": "0000947263", "category": "bank", "value_b": 86.4, "ratings": True},
    {"name": "Nomura Holdings", "cik": "0001163653", "category": "bank", "value_b": 85.4, "ratings": True},
    {"name": "Truist Financial", "cik": "0000092230", "category": "bank", "value_b": 83.7, "ratings": True},
    # --- hedge ---
    {"name": "Balyasny Asset Management", "cik": "0001218710", "category": "hedge", "value_b": 80.2, "ratings": False},
    # --- pension ---
    {"name": "New York State Common Retirement Fund", "cik": "0000810265", "category": "pension", "value_b": 79.3, "ratings": False},
    # --- quant ---
    {"name": "Renaissance Technologies", "cik": "0001037389", "category": "quant", "value_b": 72.6, "ratings": False},
    # --- pension ---
    {"name": "Healthcare of Ontario Pension Plan", "cik": "0001535845", "category": "pension", "value_b": 71.2, "ratings": False},
    {"name": "Caisse de Depot", "cik": "0000898286", "category": "pension", "value_b": 70.2, "ratings": False},
    # --- assetmgr ---
    {"name": "Brown Advisory", "cik": "0001345929", "category": "assetmgr", "value_b": 64.6, "ratings": False},
    # --- bank ---
    {"name": "Fifth Third Bancorp", "cik": "0000035527", "category": "bank", "value_b": 61.7, "ratings": True},
    # --- pension ---
    {"name": "State Board of Administration of Florida", "cik": "0000938076", "category": "pension", "value_b": 60.3, "ratings": False},
    {"name": "New York State Teachers Retirement System", "cik": "0000314969", "category": "pension", "value_b": 54.2, "ratings": False},
    {"name": "State of Wisconsin Investment Board", "cik": "0000854157", "category": "pension", "value_b": 49.6, "ratings": False},
    # --- tiger ---
    {"name": "Coatue Management", "cik": "0001135730", "category": "tiger", "value_b": 48.6, "ratings": False},
    {"name": "Soroban Capital Partners", "cik": "0001517857", "category": "tiger", "value_b": 47.8, "ratings": False},
    # --- assetmgr ---
    {"name": "Fayez Sarofim", "cik": "0000937729", "category": "assetmgr", "value_b": 42.5, "ratings": False},
    # --- tiger ---
    {"name": "Viking Global Investors", "cik": "0001103804", "category": "tiger", "value_b": 35.1, "ratings": False},
    {"name": "D1 Capital Partners", "cik": "0001747057", "category": "tiger", "value_b": 34.8, "ratings": False},
    # --- hedge ---
    {"name": "Blackstone", "cik": "0001393818", "category": "hedge", "value_b": 32.9, "ratings": False},
    # --- bank ---
    {"name": "KeyBank N.A.", "cik": "0001089877", "category": "bank", "value_b": 30.4, "ratings": True},
    # --- assetmgr ---
    {"name": "Winslow Capital Management", "cik": "0000900973", "category": "assetmgr", "value_b": 29.1, "ratings": False},
    # --- quant ---
    {"name": "WorldQuant", "cik": "0001745981", "category": "quant", "value_b": 29.1, "ratings": False},
    # --- hedge ---
    {"name": "Schonfeld Strategic Advisors", "cik": "0001665241", "category": "hedge", "value_b": 27.9, "ratings": False},
    # --- assetmgr ---
    {"name": "Sands Capital Management", "cik": "0001020066", "category": "assetmgr", "value_b": 26.9, "ratings": False},
    # --- hedge ---
    {"name": "Bridgewater Associates", "cik": "0001350694", "category": "hedge", "value_b": 24.4, "ratings": False},
    # --- tiger ---
    {"name": "Tiger Global Management", "cik": "0001167483", "category": "tiger", "value_b": 24.0, "ratings": False},
    # --- assetmgr ---
    {"name": "Davis Selected Advisers", "cik": "0001036325", "category": "assetmgr", "value_b": 23.3, "ratings": False},
    # --- bank ---
    {"name": "Macquarie Group", "cik": "0001418333", "category": "bank", "value_b": 23.2, "ratings": True},
    # --- activist ---
    {"name": "Elliott Investment Management", "cik": "0001791786", "category": "activist", "value_b": 22.7, "ratings": False},
    # --- hedge ---
    {"name": "Farallon Capital Management", "cik": "0000909661", "category": "hedge", "value_b": 21.7, "ratings": False},
    # --- biotech ---
    {"name": "Baker Bros Advisors", "cik": "0001263508", "category": "biotech", "value_b": 20.0, "ratings": False},
    # --- assetmgr ---
    {"name": "ARK Investment Management", "cik": "0001697748", "category": "assetmgr", "value_b": 15.4, "ratings": False},
    # --- biotech ---
    {"name": "RA Capital Management", "cik": "0001346824", "category": "biotech", "value_b": 11.5, "ratings": False},
    {"name": "Avoro Capital", "cik": "0001633313", "category": "biotech", "value_b": 11.1, "ratings": False},
    {"name": "Deerfield Management", "cik": "0001009258", "category": "biotech", "value_b": 9.59, "ratings": False},
    {"name": "Perceptive Advisors", "cik": "0001224962", "category": "biotech", "value_b": 6.66, "ratings": False},
    {"name": "Orbimed Advisors", "cik": "0001055951", "category": "biotech", "value_b": 5.4, "ratings": False},
    {"name": "Frazier Life Sciences", "cik": "0001892134", "category": "biotech", "value_b": 4.59, "ratings": False},
    {"name": "EcoR1 Capital", "cik": "0001587114", "category": "biotech", "value_b": 2.06, "ratings": False},
    {"name": "Rock Springs Capital", "cik": "0001595725", "category": "biotech", "value_b": 2.05, "ratings": False},
    {"name": "Casdin Capital", "cik": "0001534261", "category": "biotech", "value_b": 2.0, "ratings": False},
    {"name": "Cormorant Asset Management", "cik": "0001583977", "category": "biotech", "value_b": 1.95, "ratings": False},
    {"name": "Boxer Capital", "cik": "0001465837", "category": "biotech", "value_b": 1.5, "ratings": False},
    {"name": "Redmile Group", "cik": "0001425738", "category": "biotech", "value_b": 1.49, "ratings": False},
]

# Sub-filer CIKs that roll up to a watchlist parent (alias CIK -> parent CIK).
# Used for badge/rating lookups in `position`/`consensus`; filings and
# consensus fetching still use the parent CIK.
WATCHLIST_ALIASES: dict[str, str] = {
    # Vanguard sub-advisers (Vanguard splits its 13F across entities since 2025)
    "0002100119": "0000102909",  # Vanguard Capital Management LLC (~$4.7T)
    "0002100121": "0000102909",  # Vanguard Portfolio Management LLC (~$2.2T)
    "0000933478": "0000102909",  # Vanguard Fiduciary Trust Co (~$454B)
    "0001811242": "0000102909",  # Vanguard Global Advisers LLC (~$215B)
    "0001680208": "0000102909",  # Vanguard Asset Management, Ltd (~$148B)
    "0000947529": "0000102909",  # Vanguard Advisers Inc (~$29B)
}
