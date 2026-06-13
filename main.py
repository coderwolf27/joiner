# requirements.txt
"""
telethon==1.34.0
colorama==0.4.6
asyncio==3.4.3
"""

# config.py
import json
import os
from pathlib import Path

class Config:
    BOT_TOKEN = "8165906774:AAFYUEtSFr69bUVwW4nhMEq549EIzN4vPmU"  # Get from @BotFather
    SESSION_DIR = "sessions"
    DATA_FILE = "accounts_data.json"
    
    @staticmethod
    def ensure_dirs():
        Path(Config.SESSION_DIR).mkdir(exist_ok=True)

# database.py
import json
import asyncio
from typing import Dict, List, Any
from datetime import datetime
from config import Config

class Database:
    def __init__(self):
        self.accounts: Dict[str, Any] = {}
        self.join_logs: Dict[str, List] = {}
        self.load_data()
    
    def load_data(self):
        try:
            with open(Config.DATA_FILE, 'r') as f:
                data = json.load(f)
                self.accounts = data.get('accounts', {})
                self.join_logs = data.get('join_logs', {})
        except FileNotFoundError:
            pass
    
    def save_data(self):
        with open(Config.DATA_FILE, 'w') as f:
            json.dump({
                'accounts': self.accounts,
                'join_logs': self.join_logs
            }, f, indent=2)
    
    def add_account(self, phone: str, user_id: str, first_name: str):
        if phone not in self.accounts:
            self.accounts[phone] = {
                'user_id': user_id,
                'first_name': first_name,
                'added_on': datetime.now().isoformat(),
                'is_active': True
            }
            self.join_logs[phone] = []
            self.save_data()
    
    def log_join_result(self, phone: str, group_link: str, status: str, message: str):
        if phone not in self.join_logs:
            self.join_logs[phone] = []
        
        self.join_logs[phone].append({
            'timestamp': datetime.now().isoformat(),
            'group_link': group_link,
            'status': status,
            'message': message
        })
        self.save_data()
    
    def get_accounts(self) -> Dict:
        return {k: v for k, v in self.accounts.items() if v.get('is_active', True)}
    
    def remove_account(self, phone: str):
        if phone in self.accounts:
            self.accounts[phone]['is_active'] = False
            self.save_data()

# account_manager.py
import asyncio
from telethon import TelegramClient, errors
from telethon.tl.functions.messages import ImportChatInviteRequest, CheckChatInviteRequest
import re
from colorama import Fore, Style, init
from config import Config
from database import Database

init(autoreset=True)

class AccountManager:
    def __init__(self, db: Database):
        self.db = db
        self.clients: Dict[str, TelegramClient] = {}
        self.login_tasks = {}
    
    def extract_invite_hash(self, link: str) -> str:
        """Extract invite hash from various Telegram invite link formats"""
        patterns = [
            r'https?://t\.me/joinchat/([a-zA-Z0-9_-]+)',
            r'https?://telegram\.me/joinchat/([a-zA-Z0-9_-]+)',
            r'https?://t\.me/([a-zA-Z0-9_]+)',
            r'^([a-zA-Z0-9_-]+)$'
        ]
        
        for pattern in patterns:
            match = re.search(pattern, link)
            if match:
                return match.group(1)
        return None
    
    async def login_account(self, phone: str, code_callback, password_callback=None):
        """Login to a Telegram account"""
        session_file = f"{Config.SESSION_DIR}/{phone}"
        client = TelegramClient(session_file, api_id, api_hash)
        
        try:
            await client.connect()
            
            if not await client.is_user_authorized():
                await client.send_code_request(phone)
                code = await code_callback()
                
                try:
                    await client.sign_in(phone, code)
                except errors.SessionPasswordNeededError:
                    if password_callback:
                        password = await password_callback()
                        await client.sign_in(password=password)
                    else:
                        raise Exception("2FA password required")
            
            me = await client.get_me()
            self.clients[phone] = client
            self.db.add_account(phone, str(me.id), me.first_name)
            
            return {"success": True, "user": me.first_name}
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    async def join_group(self, client: TelegramClient, link: str, phone: str) -> dict:
        """Join a Telegram group using invite link"""
        try:
            invite_hash = self.extract_invite_hash(link)
            if not invite_hash:
                return {"status": "invalid_link", "message": "Invalid invite link format"}
            
            # Check if already joined
            try:
                result = await client(CheckChatInviteRequest(hash=invite_hash))
                if hasattr(result, 'chat') and result.chat:
                    if hasattr(result.chat, 'participants_count'):
                        return {"status": "already_member", "message": f"Already a member of {result.chat.title}"}
            except Exception:
                pass
            
            # Join the group
            result = await client(ImportChatInviteRequest(invite_hash))
            
            if result.chats:
                chat = result.chats[0]
                return {
                    "status": "success",
                    "message": f"Successfully joined {chat.title}",
                    "chat_title": chat.title
                }
            else:
                return {"status": "error", "message": "Failed to join group"}
                
        except errors.InviteHashExpiredError:
            return {"status": "expired", "message": "Invite link has expired"}
        except errors.InviteHashInvalidError:
            return {"status": "invalid", "message": "Invalid invite link"}
        except errors.UserAlreadyParticipantError:
            return {"status": "already_member", "message": "Already a member of this group"}
        except errors.FloodWaitError as e:
            return {"status": "flood_wait", "message": f"Rate limited. Wait {e.seconds} seconds"}
        except Exception as e:
            return {"status": "error", "message": f"Unexpected error: {str(e)}"}
    
    async def join_groups_for_account(self, phone: str, group_links: list, progress_callback=None):
        """Join multiple groups for a specific account"""
        if phone not in self.clients:
            return {"success": False, "error": "Account not logged in"}
        
        client = self.clients[phone]
        results = []
        
        for idx, link in enumerate(group_links):
            if progress_callback:
                await progress_callback(idx + 1, len(group_links), link)
            
            result = await self.join_group(client, link, phone)
            self.db.log_join_result(phone, link, result['status'], result['message'])
            results.append({
                'link': link,
                **result
            })
            
            # Add small delay between joins to avoid rate limiting
            await asyncio.sleep(2)
        
        return {"success": True, "results": results}
    
    async def logout_account(self, phone: str):
        """Logout and remove account"""
        if phone in self.clients:
            await self.clients[phone].disconnect()
            del self.clients[phone]
        self.db.remove_account(phone)

# bot.py
import asyncio
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, ConversationHandler, filters, ContextTypes
from config import Config
from database import Database
from account_manager import AccountManager
import os

# Conversation states
PHONE_NUMBER, LOGIN_CODE, LOGIN_PASSWORD, WAITING_GROUPS = range(4)

class TelegramBot:
    def __init__(self):
        Config.ensure_dirs()
        self.db = Database()
        self.account_manager = AccountManager(self.db)
        self.pending_logins = {}
        self.pending_groups = {}
    
    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Start command handler"""
        keyboard = [
            [InlineKeyboardButton("➕ Add Account", callback_data='add_account')],
            [InlineKeyboardButton("📋 List Accounts", callback_data='list_accounts')],
            [InlineKeyboardButton("🔗 Join Groups", callback_data='join_groups')],
            [InlineKeyboardButton("📊 View Logs", callback_data='view_logs')],
            [InlineKeyboardButton("❌ Remove Account", callback_data='remove_account')]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(
            "🤖 *Telegram Group Joiner Bot*\n\n"
            "I can help you automatically join Telegram groups using multiple accounts.\n\n"
            "Choose an option below:",
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )
    
    async def button_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle button clicks"""
        query = update.callback_query
        await query.answer()
        
        if query.data == 'add_account':
            await query.edit_message_text(
                "📱 *Add New Account*\n\n"
                "Please enter your phone number in international format.\n"
                "Example: +1234567890\n\n"
                "Send /cancel to cancel.",
                parse_mode='Markdown'
            )
            return ConversationHandler.END
            # return PHONE_NUMBER
        
        elif query.data == 'list_accounts':
            accounts = self.db.get_accounts()
            if not accounts:
                await query.edit_message_text("No accounts added yet. Use 'Add Account' to add one.")
            else:
                msg = "*📱 Your Accounts:*\n\n"
                for phone, info in accounts.items():
                    msg += f"• `{phone}` - {info['first_name']}\n"
                await query.edit_message_text(msg, parse_mode='Markdown')
        
        elif query.data == 'join_groups':
            accounts = self.db.get_accounts()
            if not accounts:
                await query.edit_message_text("No accounts available. Please add an account first.")
                return
            
            keyboard = []
            for phone, info in accounts.items():
                keyboard.append([InlineKeyboardButton(
                    f"{info['first_name']} ({phone})", 
                    callback_data=f"select_account_{phone}"
                )])
            keyboard.append([InlineKeyboardButton("🔙 Back", callback_data='back')])
            
            await query.edit_message_text(
                "Select account(s) to join groups:\n"
                "(You'll be asked to provide group links after selection)",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
        
        elif query.data.startswith('select_account_'):
            phone = query.data.replace('select_account_', '')
            
            if 'selected_accounts' not in context.user_data:
                context.user_data['selected_accounts'] = []
            
            if phone in context.user_data['selected_accounts']:
                context.user_data['selected_accounts'].remove(phone)
                action = "deselected"
            else:
                context.user_data['selected_accounts'].append(phone)
                action = "selected"
            
            accounts = self.db.get_accounts()
            keyboard = []
            for acc_phone, info in accounts.items():
                check = "✅ " if acc_phone in context.user_data['selected_accounts'] else ""
                keyboard.append([InlineKeyboardButton(
                    f"{check}{info['first_name']} ({acc_phone})", 
                    callback_data=f"select_account_{acc_phone}"
                )])
            
            if context.user_data['selected_accounts']:
                keyboard.append([InlineKeyboardButton("🚀 Continue to Groups", callback_data='continue_to_groups')])
            keyboard.append([InlineKeyboardButton("🔙 Back", callback_data='back')])
            
            await query.edit_message_text(
                f"Selected {len(context.user_data['selected_accounts'])} account(s).\n"
                f"Tap again to deselect.\n\n"
                f"**Current selection:**\n" + 
                "\n".join([f"• {p}" for p in context.user_data['selected_accounts']]),
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode='Markdown'
            )
        
        elif query.data == 'continue_to_groups':
            if not context.user_data.get('selected_accounts'):
                await query.edit_message_text("Please select at least one account first.")
                return
            
            await query.edit_message_text(
                "📝 *Send Group Links*\n\n"
                "Please send the group links you want to join.\n"
                "You can send multiple links separated by newlines.\n\n"
                "Example:\n"
                "https://t.me/joinchat/abc123\n"
                "https://t.me/joinchat/def456\n\n"
                "Send /cancel to cancel.",
                parse_mode='Markdown'
            )
            context.user_data['waiting_for_groups'] = True
            return WAITING_GROUPS
        
        elif query.data == 'view_logs':
            accounts = self.db.get_accounts()
            if not accounts:
                await query.edit_message_text("No accounts found.")
                return
            
            keyboard = [[InlineKeyboardButton(info['first_name'], callback_data=f"logs_{phone}")] 
                       for phone, info in accounts.items()]
            keyboard.append([InlineKeyboardButton("🔙 Back", callback_data='back')])
            
            await query.edit_message_text(
                "Select account to view join logs:",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
        
        elif query.data.startswith('logs_'):
            phone = query.data.replace('logs_', '')
            logs = self.db.join_logs.get(phone, [])
            
            if not logs:
                await query.edit_message_text(f"No join logs for {phone}")
                return
            
            msg = f"📊 *Join Logs for {phone}*\n\n"
            for log in logs[-10:]:  # Last 10 entries
                status_emoji = {
                    'success': '✅',
                    'invalid_link': '❌',
                    'expired': '⏰',
                    'already_member': '👥',
                    'error': '⚠️'
                }.get(log['status'], '❓')
                
                msg += f"{status_emoji} `{log['group_link']}`\n"
                msg += f"   {log['message']}\n\n"
            
            await query.edit_message_text(msg, parse_mode='Markdown')
        
        elif query.data == 'remove_account':
            accounts = self.db.get_accounts()
            if not accounts:
                await query.edit_message_text("No accounts to remove.")
                return
            
            keyboard = [[InlineKeyboardButton(info['first_name'], callback_data=f"remove_{phone}")] 
                       for phone, info in accounts.items()]
            keyboard.append([InlineKeyboardButton("🔙 Back", callback_data='back')])
            
            await query.edit_message_text(
                "Select account to remove:",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
        
        elif query.data.startswith('remove_'):
            phone = query.data.replace('remove_', '')
            await self.account_manager.logout_account(phone)
            await query.edit_message_text(f"✅ Account {phone} has been removed.")
        
        elif query.data == 'back':
            await self.start(update, context)
        
        return ConversationHandler.END
    
    async def handle_groups(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle group links input"""
        if not context.user_data.get('waiting_for_groups'):
            return ConversationHandler.END
        
        group_links = update.message.text.strip().split('\n')
        group_links = [link.strip() for link in group_links if link.strip()]
        
        selected_accounts = context.user_data.get('selected_accounts', [])
        
        progress_msg = await update.message.reply_text(
            f"🚀 Starting to join {len(group_links)} groups using {len(selected_accounts)} accounts...\n"
            f"This may take a while."
        )
        
        all_results = {}
        
        for phone in selected_accounts:
            await progress_msg.edit_text(f"Processing account: {phone}\nJoining groups...")
            
            result = await self.account_manager.join_groups_for_account(phone, group_links)
            all_results[phone] = result
        
        # Generate summary
        summary = "*📊 Join Summary*\n\n"
        for phone, result in all_results.items():
            if result['success']:
                success_count = sum(1 for r in result['results'] if r['status'] == 'success')
                summary += f"**{phone}:** {success_count}/{len(group_links)} successful\n"
            else:
                summary += f"**{phone}:** Failed - {result['error']}\n"
        
        await progress_msg.edit_text(summary, parse_mode='Markdown')
        
        # Send detailed report
        for phone, result in all_results.items():
            if result['success']:
                report = f"*Detailed Report for {phone}:*\n\n"
                for r in result['results']:
                    status_icon = {
                        'success': '✅',
                        'invalid_link': '❌',
                        'expired': '⏰',
                        'already_member': '👥',
                        'error': '⚠️'
                    }.get(r['status'], '❓')
                    report += f"{status_icon} {r['link']}\n   {r['message']}\n\n"
                
                await update.message.reply_text(report, parse_mode='Markdown')
        
        context.user_data['waiting_for_groups'] = False
        context.user_data['selected_accounts'] = []
        return ConversationHandler.END
    
    async def cancel(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Cancel conversation"""
        context.user_data.clear()
        await update.message.reply_text("Operation cancelled. Use /start to begin again.")
        return ConversationHandler.END

# main.py
import asyncio
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, ConversationHandler, filters
from config import Config
from bot import TelegramBot, PHONE_NUMBER, LOGIN_CODE, LOGIN_PASSWORD, WAITING_GROUPS

# IMPORTANT: You need to get these from https://my.telegram.org
API_ID = 29687194  # Replace with your API ID
API_HASH = "fb286056a72033e9870cacb170b31fcd"  # Replace with your API Hash

async def main():
    # Initialize bot
    telegram_bot = TelegramBot()
    
    # Create application
    application = Application.builder().token(Config.BOT_TOKEN).build()
    
    # Add handlers
    application.add_handler(CommandHandler("start", telegram_bot.start))
    application.add_handler(CallbackQueryHandler(telegram_bot.button_handler))
    
    # Group links conversation
    conv_handler = ConversationHandler(
        entry_points=[CallbackQueryHandler(telegram_bot.button_handler, pattern='continue_to_groups')],
        states={
            WAITING_GROUPS: [MessageHandler(filters.TEXT & ~filters.COMMAND, telegram_bot.handle_groups)],
        },
        fallbacks=[CommandHandler("cancel", telegram_bot.cancel)]
    )
    application.add_handler(conv_handler)
    
    # Start bot
    print("Bot is starting...")
    await application.initialize()
    await application.start()
    await application.updater.start_polling()
    
    print("Bot is running! Press Ctrl+C to stop.")
    
    # Keep running
    try:
        await asyncio.Event().wait()
    except KeyboardInterrupt:
        print("\nShutting down...")
        await application.stop()

if __name__ == "__main__":
    # Set your credentials here or use environment variables
    API_ID = os.getenv('TELEGRAM_API_ID', API_ID)
    API_HASH = os.getenv('TELEGRAM_API_HASH', API_HASH)
    
    if API_ID == 123456 or API_HASH == "your_api_hash_here":
        print("⚠️ WARNING: Please set your API_ID and API_HASH in main.py")
        print("Get them from https://my.telegram.org")
        exit(1)
    
    # Import API credentials to account_manager
    import account_manager
    account_manager.api_id = API_ID
    account_manager.api_hash = API_HASH
    
    asyncio.run(main())
