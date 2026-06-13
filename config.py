# config.py
import os
from dotenv import load_dotenv

load_dotenv()

class Config:
    # Bot Token from @BotFather
    BOT_TOKEN = os.getenv('BOT_TOKEN', '8165906774:AAFYUEtSFr69bUVwW4nhMEq549EIzN4vPmU')
    
    # API credentials from my.telegram.org
    API_ID = int(os.getenv('API_ID', '29687194'))
    API_HASH = os.getenv('API_HASH', 'fb286056a72033e9870cacb170b31fcd')
    
    # Directories
    SESSION_DIR = 'sessions'
    DATA_DIR = 'data'
    
    # Files
    GROUPS_FILE = os.path.join(DATA_DIR, 'groups.json')
    ACCOUNTS_FILE = os.path.join(DATA_DIR, 'accounts.json')
    JOIN_QUEUE_FILE = os.path.join(DATA_DIR, 'join_queue.json')
    
    # Create directories
    os.makedirs(SESSION_DIR, exist_ok=True)
    os.makedirs(DATA_DIR, exist_ok=True)
