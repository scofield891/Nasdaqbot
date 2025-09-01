import yfinance as yf
import pandas as pd
import telegram
import logging
import asyncio
from datetime import datetime
import pytz
import os
import requests
from bs4 import BeautifulSoup
import json
import random  # Sentiment simülasyonu için, gerçekte x_semantic_search kullan

# Sabit Değerler
BOT_TOKEN = os.getenv("BOT_TOKEN", "7692932890:AAGrN_ebS9anjxOqSI9QlVDRQ7WCrIkvUqI")
CHAT_ID = os.getenv("CHAT_ID", "-1003006970573")  # Senin chat ID'n
TEST_MODE = False
MARKET_CAP_MIN = 250000000  # 250M
MARKET_CAP_MAX = 5000000000  # 5B
MARKET_CAP_SPLIT = 2000000000  # 2B
EPS_GROWTH_MIN = 0.30
REVENUE_GROWTH_MIN = 0.20
PE_MIN = 10
PE_MAX = 60
DEBT_EQUITY_MAX = 1.0
ROE_MIN = 0.15
SURPRISE_MIN = 0.0
SENTIMENT_MIN = 0.60
PREVIOUS_DATA_FILE = 'previous_data.json'  # Değişim izleme için
SCORE_MIN = 60  # Test için 60, normalde 70

# Logging
logger = logging.getLogger()
logger.setLevel(logging.INFO)
formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
console_handler = logging.StreamHandler()
console_handler.setFormatter(formatter)
logger.addHandler(console_handler)
file_handler = logging.FileHandler('bot.log')
file_handler.setFormatter(formatter)
logger.addHandler(file_handler)

# Telegram Bot
telegram_bot = telegram.Bot(token=BOT_TOKEN)

# Hisse Listesi Çekme (Nasdaq ve S&P 500)
def get_stock_list():
    # Nasdaq listesi
    url_nasdaq = "https://stockanalysis.com/list/nasdaq-stocks/"
    response = requests.get(url_nasdaq)
    soup = BeautifulSoup(response.text, 'html.parser')
    table = soup.find('table')
    nasdaq_df = pd.read_html(str(table))[0]
    nasdaq_symbols = nasdaq_df['Symbol'].tolist()

    # S&P 500 listesi
    url_sp = "https://stockanalysis.com/list/sp-500-stocks/"
    response = requests.get(url_sp)
    soup = BeautifulSoup(response.text, 'html.parser')
    table = soup.find('table')
    sp_df = pd.read_html(str(table))[0]
    sp_symbols = sp_df['Symbol'].tolist()

    # Unique liste
    all_symbols = list(set(nasdaq_symbols + sp_symbols))
    return all_symbols

# Temel Verileri Çekme ve Filtreleme
def get_fundamentals(symbols):
    candidates = []
    for i in range(0, len(symbols), 50):  # Batch'i 50'ye düşürdüm, rate limit için
        batch = symbols[i:i+50]
        for symbol in batch:
            try:
                ticker = yf.Ticker(symbol)
                info = ticker.info
                market_cap = info.get('marketCap', 0)
                if not (MARKET_CAP_MIN < market_cap < MARKET_CAP_MAX):
                    continue

                eps_growth = info.get('earningsQuarterlyGrowth', 0)
                revenue_growth = info.get('revenueGrowth', 0)
                pe = info.get('forwardPE', float('nan'))
                debt_equity = info.get('debtToEquity', float('nan'))
                roe = info.get('returnOnEquity', 0)

                # Surprise'ı optional yap
                earnings_dates = ticker.earnings_dates
                surprise = 0
                if not earnings_dates.empty and 'Surprise' in earnings_dates.columns:
                    surprise = earnings_dates.iloc[0]['Surprise']
                else:
                    logger.warning(f"{symbol} surprise verisi yok, 0 kabul edildi.")

                # Sentiment (Gerçekte x_semantic_search tool'u kullan, burada simüle)
                sentiment = get_sentiment(symbol)

                score = 0
                if eps_growth > EPS_GROWTH_MIN: score += 30
                if revenue_growth > REVENUE_GROWTH_MIN: score += 25
                if PE_MIN <= pe <= PE_MAX: score += 15
                if debt_equity < DEBT_EQUITY_MAX: score += 10
                if roe > ROE_MIN: score += 10
                if surprise > SURPRISE_MIN: score += 5
                if sentiment > SENTIMENT_MIN: score += 5

                if score > SCORE_MIN:
                    candidates.append({
                        'symbol': symbol,
                        'cap': market_cap,
                        'score': score,
                        'eps': eps_growth,
                        'revenue': revenue_growth,
                        'pe': pe,
                        'debt': debt_equity,
                        'roe': roe,
                        'surprise': surprise,
                        'sentiment': sentiment
                    })
            except Exception as e:
                logger.error(f"{symbol} hata: {e}")
    return pd.DataFrame(candidates)

# Sentiment Çekme (Gerçek botta x_semantic_search çağr, burada simüle)
def get_sentiment(symbol):
    # Gerçekte: x_semantic_search(query=f"positive sentiment {symbol} stock 2025", limit=10) ile skorla
    # Şimdilik rastgele simüle (0.5-0.8)
    return random.uniform(0.5, 0.8)

# Önceki Veriyi Yükle ve Değişim Bul
def detect_changes(current_df):
    if os.path.exists(PREVIOUS_DATA_FILE):
        with open(PREVIOUS_DATA_FILE, 'r') as f:
            previous = json.load(f)
        previous_df = pd.DataFrame(previous)
        changes = []
        for symbol in previous_df['symbol']:
            if symbol not in current_df['symbol'].values:
                changes.append(f"{symbol} listeden çıktı (temel veriler kriterleri karşılamadı).")
            else:
                prev_eps = previous_df[previous_df['symbol'] == symbol]['eps'].values[0]
                curr_eps = current_df[current_df['symbol'] == symbol]['eps'].values[0]
                if curr_eps < prev_eps - 0.1:  # %10 düşüş
                    changes.append(f"{symbol} EPS %{prev_eps*100:.0f} -> %{curr_eps*100:.0f}, portföyden çıkar.")
        return changes
    return []

# Önceki Veriyi Kaydet
def save_previous(current_df):
    with open(PREVIOUS_DATA_FILE, 'w') as f:
        json.dump(current_df.to_dict('records'), f)

# Ana Fonksiyon (Cron ile Çalışacak)
async def main():
    tz = pytz.timezone('Europe/Istanbul')
    now = datetime.now(tz)
    symbols = get_stock_list()
    df = get_fundamentals(symbols)
    changes = detect_changes(df)
    save_previous(df)

    if df.empty:
        message = "Bu hafta kriterlere uyan hisse yok."
    else:
        df_less_2b = df[df['cap'] < MARKET_CAP_SPLIT].sort_values('score', ascending=False).head(15)
        df_2b_5b = df[df['cap'] >= MARKET_CAP_SPLIT].sort_values('score', ascending=False).head(15)
        
        message = f"Pazartesi {now.strftime('%H:%M')} - Top 30 Baby Hisse (1-2 Yıl Patlama)\n\n<2B Hisseler:\n"
        for i, row in df_less_2b.iterrows():
            message += f"{i+1}. {row['symbol']} (Cap: {row['cap']/1e9:.1f}B, Puan: {row['score']}/100)\n"
            message += f"   Sebepler: EPS %{row['eps']*100:.0f} (büyüme), revenue %{row['revenue']*100:.0f}, P/E {row['pe']:.0f}, debt/equity {row['debt']:.1f}, ROE %{row['roe']*100:.0f}, surprise +{row['surprise']:.1f}%, sentiment {row['sentiment']*100:.0f}% pozitif.\n"
        
        message += "\n2B-5B Hisseler:\n"
        for i, row in df_2b_5b.iterrows():
            message += f"{i+1}. {row['symbol']} (Cap: {row['cap']/1e9:.1f}B, Puan: {row['score']}/100)\n"
            message += f"   Sebepler: EPS %{row['eps']*100:.0f} (büyüme), revenue %{row['revenue']*100:.0f}, P/E {row['pe']:.0f}, debt/equity {row['debt']:.1f}, ROE %{row['roe']*100:.0f}, surprise +{row['surprise']:.1f}%, sentiment {row['sentiment']*100:.0f}% pozitif.\n"
        
        if changes:
            message += "\nDeğişimler:\n" + "\n".join(changes)

    await telegram_bot.send_message(chat_id=CHAT_ID, text=message)
    logger.info("Mesaj gönderildi.")

if __name__ == "__main__":
    asyncio.run(main())
