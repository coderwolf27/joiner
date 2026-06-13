# telegram_group_joiner_debug.py
# Complete bot with extensive logging

import os
import json
import asyncio
import re
import logging
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Any
from telethon import TelegramClient, errors
from telethon.tl.functions.messages import ImportChatInviteRequest
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, ConversationHandler, filters, ContextTypes

# Enable detailed logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ==================== CONFIGURATION ====================
# IMPORTANT: Replace these with your actual values
BOT_TOKEN = "8165906774:AAFYUEtSFr69bUVwW4nhMEq549EIzN4vPmU"  # Get from @BotFather
API_ID = 29687194  # Get from https://my.telegram.org
API_HASH = "fb286056a72033e9870cacb170b31fcd"  # Get from https://my.telegram.org

# File paths
SESSION_DIR = "sessions"
DATA_FILE = "accounts_data.json"

# Conversation states
PHONE_NUMBER, LOGIN_CODE, LOGIN_PASSWORD, WAITING_GROUPS = range(4)

# ==================== DATABASE CLASS ====================
class Database:
    def __init__(self):
        self.accounts: Dict[str, Any] = {}
        self.join_logs: Dict[str, List] = {}
        self.ensure_dirs()
        self.load_data()
        logger.info("Database initialized")
    
    def ensure_dirs(self):
        Path(SESSION_DIR).mkdir(exist_ok=True)
    
    def load_data(self):
        try:
            with open(DATA_FILE, 'r') as f:
                data = json.load(f)
                self.accounts = data.get('accounts', {})
                self.join_logs = data.get('join_logs', {})
                logger.info(f"Loaded {len(self.accounts)} accounts from database")
        except FileNotFoundError:
            logger.info("No existing database found, creating new one")
            pass
    
    def save_data(self):
        with open(DATA_FILE, 'w') as f:
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
            logger.info(f"Added account: {phone} - {first_name}")
    
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
            logger.info(f"Removed account: {phone}")
    
    def delete_account(self, phone: str):
        if phone in self.accounts:
            del self.accounts[phone]
            if phone in self.join_logs:
                del self.join_logs[phone]
            self.save_data()
            logger.info(f"Deleted account: {phone}")

# ==================== ACCOUNT MANAGER ====================
class AccountManager:
    def __init__(self, db: Database):
        self.db = db
        self.clients: Dict[str, TelegramClient] = {}
        logger.info("AccountManager initialized")
    
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
    
    async def login_account(self, phone: str, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Login to a Telegram account with proper async handling"""
        logger.info(f"Starting login process for phone: {phone}")
        
        session_file = f"{SESSION_DIR}/{phone.replace('+', '')}"
        logger.info(f"Session file path: {session_file}")
        
        client = TelegramClient(session_file, API_ID, API_HASH)
        
        try:
            # Send initial message
            await update.message.reply_text(f"📱 Connecting to {phone}...\n\n⚙️ This may take a few seconds...")
            logger.info(f"Connecting client for {phone}")
            
            await client.connect()
            logger.info(f"Client connected for {phone}")
            
            if not await client.is_user_authorized():
                logger.info(f"User not authorized, sending code request to {phone}")
                
                # Send code request
                try:
                    await client.send_code_request(phone)
                    logger.info(f"Code request sent successfully to {phone}")
                    
                    await update.message.reply_text(
                        f"✅ Verification code sent to {phone}\n\n"
                        f"📝 Please check your Telegram app and enter the code you received:\n"
                        f"(The code usually starts with a number and might be in your Telegram chats)"
                    )
                    
                    # Store client in context
                    context.user_data['temp_client'] = client
                    context.user_data['temp_phone'] = phone
                    logger.info(f"Waiting for code input for {phone}")
                    return LOGIN_CODE
                    
                except errors.PhoneNumberInvalidError:
                    logger.error(f"Invalid phone number: {phone}")
                    await update.message.reply_text(
                        "❌ *Invalid Phone Number*\n\n"
                        "The phone number format is incorrect or not registered on Telegram.\n"
                        "Please use international format: `+1234567890`\n\n"
                        "Send /cancel to cancel.",
                        parse_mode='Markdown'
                    )
                    return ConversationHandler.END
                    
                except errors.FloodWaitError as e:
                    logger.error(f"Flood wait error: {e.seconds} seconds")
                    await update.message.reply_text(
                        f"⚠️ *Too Many Attempts*\n\n"
                        f"Please wait {e.seconds} seconds before trying again.\n"
                        f"Send /cancel to cancel.",
                        parse_mode='Markdown'
                    )
                    return ConversationHandler.END
                    
            else:
                # Already logged in
                logger.info(f"User already authorized for {phone}")
                me = await client.get_me()
                self.clients[phone] = client
                self.db.add_account(phone, str(me.id), me.first_name)
                await update.message.reply_text(
                    f"✅ *Already logged in!*\n\n"
                    f"Welcome back {me.first_name}!\n"
                    f"Phone: {phone}\n\n"
                    f"Use /start to continue.",
                    parse_mode='Markdown'
                )
                logger.info(f"Login completed (existing session) for {phone}")
                return ConversationHandler.END
                
        except errors.ApiIdInvalidError:
            logger.error("API ID or API Hash is invalid")
            await update.message.reply_text(
                "❌ *Configuration Error*\n\n"
                "Invalid API ID or API Hash.\n"
                "Please check your credentials in the script.",
                parse_mode='Markdown'
            )
            return ConversationHandler.END
            
        except Exception as e:
            logger.error(f"Unexpected error during login: {str(e)}", exc_info=True)
            await update.message.reply_text(
                f"❌ *Connection Error*\n\n"
                f"Error: {str(e)}\n\n"
                f"Please check:\n"
                f"1. Your internet connection\n"
                f"2. API ID and Hash are correct\n"
                f"3. Phone number format is correct\n\n"
                f"Send /cancel to cancel.",
                parse_mode='Markdown'
            )
            return ConversationHandler.END
    
    async def verify_code(self, code: str, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Verify the login code"""
        logger.info(f"Verifying code for phone: {context.user_data.get('temp_phone')}")
        
        client = context.user_data.get('temp_client')
        phone = context.user_data.get('temp_phone')
        
        if not client:
            logger.error("Session expired - no client found")
            await update.message.reply_text(
                "❌ Session expired. Please start over with /start"
            )
            return ConversationHandler.END
        
        try:
            logger.info(f"Attempting to sign in with code for {phone}")
            await client.sign_in(phone, code)
            logger.info(f"Sign in successful for {phone}")
            
            me = await client.get_me()
            logger.info(f"Got user info: {me.first_name} (ID: {me.id})")
            
            self.clients[phone] = client
            self.db.add_account(phone, str(me.id), me.first_name)
            
            await update.message.reply_text(
                f"✅ *Login Successful!*\n\n"
                f"Welcome {me.first_name}!\n"
                f"Phone: {phone}\n"
                f"User ID: {me.id}\n\n"
                f"🎉 Account added successfully!\n"
                f"Use /start to continue.",
                parse_mode='Markdown'
            )
            
            # Cleanup
            del context.user_data['temp_client']
            del context.user_data['temp_phone']
            logger.info(f"Login completed for {phone}")
            return ConversationHandler.END
            
        except errors.SessionPasswordNeededError:
            logger.info(f"2FA password required for {phone}")
            await update.message.reply_text(
                "🔐 *2FA Password Required*\n\n"
                "This account has two-factor authentication enabled.\n"
                "Please enter your password:",
                parse_mode='Markdown'
            )
            context.user_data['needs_password'] = True
            return LOGIN_PASSWORD
            
        except errors.PhoneCodeInvalidError:
            logger.warning(f"Invalid code entered for {phone}")
            await update.message.reply_text(
                "❌ *Invalid Code*\n\n"
                "The verification code you entered is incorrect.\n"
                "Please try again with /start",
                parse_mode='Markdown'
            )
            return ConversationHandler.END
            
        except errors.PhoneCodeExpiredError:
            logger.warning(f"Code expired for {phone}")
            await update.message.reply_text(
                "❌ *Code Expired*\n\n"
                "The verification code has expired.\n"
                "Please start over with /start",
                parse_mode='Markdown'
            )
            return ConversationHandler.END
            
        except Exception as e:
            logger.error(f"Error verifying code: {str(e)}", exc_info=True)
            await update.message.reply_text(
                f"❌ *Verification Error*\n\n"
                f"Error: {str(e)}\n\n"
                f"Please try again with /start",
                parse_mode='Markdown'
            )
            return ConversationHandler.END
    
    async def verify_password(self, password: str, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Verify 2FA password"""
        logger.info(f"Verifying 2FA password for phone: {context.user_data.get('temp_phone')}")
        
        client = context.user_data.get('temp_client')
        phone = context.user_data.get('temp_phone')
        
        if not client:
            logger.error("Session expired - no client found for 2FA")
            await update.message.reply_text(
                "❌ Session expired. Please start over with /start"
            )
            return ConversationHandler.END
        
        try:
            logger.info(f"Attempting to sign in with password for {phone}")
            await client.sign_in(password=password)
            logger.info(f"Password sign in successful for {phone}")
            
            me = await client.get_me()
            self.clients[phone] = client
            self.db.add_account(phone, str(me.id), me.first_name)
            
            await update.message.reply_text(
                f"✅ *Login Successful!*\n\n"
                f"Welcome {me.first_name}!\n"
                f"Phone: {phone}\n\n"
                f"Use /start to continue.",
                parse_mode='Markdown'
            )
            
            # Cleanup
            del context.user_data['temp_client']
            del context.user_data['temp_phone']
            del context.user_data['needs_password']
            logger.info(f"2FA login completed for {phone}")
            return ConversationHandler.END
            
        except errors.PasswordHashInvalidError:
            logger.warning(f"Invalid password for {phone}")
            await update.message.reply_text(
                "❌ *Invalid Password*\n\n"
                "The 2FA password you entered is incorrect.\n"
                "Please try again with /start",
                parse_mode='Markdown'
            )
            return ConversationHandler.END
            
        except Exception as e:
            logger.error(f"Error verifying password: {str(e)}", exc_info=True)
            await update.message.reply_text(
                f"❌ *Password Error*\n\n"
                f"Error: {str(e)}\n\n"
                f"Please try again with /start",
                parse_mode='Markdown'
            )
            return ConversationHandler.END
    
    async def join_group(self, client: TelegramClient, link: str, phone: str) -> dict:
        """Join a Telegram group using invite link"""
        try:
            invite_hash = self.extract_invite_hash(link)
            if not invite_hash:
                return {"status": "invalid_link", "message": "Invalid invite link format"}
            
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
        logger.info(f"Joining {len(group_links)} groups for account {phone}")
        
        if phone not in self.clients:
            # Try to reconnect
            session_file = f"{SESSION_DIR}/{phone.replace('+', '')}"
            client = TelegramClient(session_file, API_ID, API_HASH)
            await client.connect()
            
            if await client.is_user_authorized():
                self.clients[phone] = client
                logger.info(f"Reconnected to account {phone}")
            else:
                logger.error(f"Account {phone} not logged in")
                return {"success": False, "error": "Account not logged in"}
        
        client = self.clients[phone]
        results = []
        
        for idx, link in enumerate(group_links):
            if progress_callback:
                await progress_callback(idx + 1, len(group_links), link)
            
            logger.info(f"Joining {link} for account {phone}")
            result = await self.join_group(client, link, phone)
            self.db.log_join_result(phone, link, result['status'], result['message'])
            results.append({
                'link': link,
                **result
            })
            
            # Add small delay between joins to avoid rate limiting
            await asyncio.sleep(2)
        
        logger.info(f"Completed joining for account {phone}")
        return {"success": True, "results": results}
    
    async def logout_account(self, phone: str):
        """Logout and remove account"""
        logger.info(f"Logging out account {phone}")
        if phone in self.clients:
            await self.clients[phone].disconnect()
            del self.clients[phone]
        self.db.delete_account(phone)

# ==================== BOT HANDLER ====================
class TelegramBot:
    def __init__(self):
        self.db = Database()
        self.account_manager = AccountManager(self.db)
        logger.info("TelegramBot initialized")
    
    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Start command handler"""
        logger.info(f"Start command from user {update.effective_user.id}")
        
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
        
        logger.info(f"Button clicked: {query.data} by user {update.effective_user.id}")
        
        if query.data == 'add_account':
            await query.edit_message_text(
                "📱 *Add New Account*\n\n"
                "Please send your phone number in international format.\n"
                "Example: `+1234567890`\n\n"
                "⚠️ Make sure:\n"
                "• Include country code\n"
                "• Start with +\n"
                "• No spaces or special characters\n\n"
                "Send /cancel to cancel.",
                parse_mode='Markdown'
            )
            return PHONE_NUMBER
        
        elif query.data == 'list_accounts':
            accounts = self.db.get_accounts()
            if not accounts:
                await query.edit_message_text("❌ No accounts added yet. Use 'Add Account' to add one.")
            else:
                msg = "*📱 Your Accounts:*\n\n"
                for phone, info in accounts.items():
                    msg += f"• `{phone}` - {info['first_name']}\n"
                await query.edit_message_text(msg, parse_mode='Markdown')
            return ConversationHandler.END
        
        elif query.data == 'join_groups':
            accounts = self.db.get_accounts()
            if not accounts:
                await query.edit_message_text("❌ No accounts available. Please add an account first.")
                return ConversationHandler.END
            
            keyboard = []
            for phone, info in accounts.items():
                keyboard.append([InlineKeyboardButton(
                    f"{info['first_name']} ({phone})", 
                    callback_data=f"select_account_{phone}"
                )])
            keyboard.append([InlineKeyboardButton("🔙 Back", callback_data='back')])
            
            await query.edit_message_text(
                "📋 *Select Accounts*\n\n"
                "Select account(s) to join groups:\n"
                "(You'll be asked to provide group links after selection)",
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode='Markdown'
            )
            return ConversationHandler.END
        
        elif query.data.startswith('select_account_'):
            phone = query.data.replace('select_account_', '')
            
            if 'selected_accounts' not in context.user_data:
                context.user_data['selected_accounts'] = []
            
            if phone in context.user_data['selected_accounts']:
                context.user_data['selected_accounts'].remove(phone)
            else:
                context.user_data['selected_accounts'].append(phone)
            
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
            
            selected_text = "\n".join([f"• {p}" for p in context.user_data['selected_accounts']]) if context.user_data['selected_accounts'] else "None"
            
            await query.edit_message_text(
                f"*Selected Accounts:* {len(context.user_data['selected_accounts'])}\n\n"
                f"{selected_text}\n\n"
                f"Tap again to deselect.",
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode='Markdown'
            )
            return ConversationHandler.END
        
        elif query.data == 'continue_to_groups':
            if not context.user_data.get('selected_accounts'):
                await query.edit_message_text("❌ Please select at least one account first.")
                return ConversationHandler.END
            
            await query.edit_message_text(
                "📝 *Send Group Links*\n\n"
                "Please send the group links you want to join.\n"
                "You can send multiple links separated by newlines.\n\n"
                "Example:\n"
                "`https://t.me/joinchat/abc123`\n"
                "`https://t.me/joinchat/def456`\n\n"
                "Send /cancel to cancel.",
                parse_mode='Markdown'
            )
            context.user_data['waiting_for_groups'] = True
            return WAITING_GROUPS
        
        elif query.data == 'view_logs':
            accounts = self.db.get_accounts()
            if not accounts:
                await query.edit_message_text("❌ No accounts found.")
                return ConversationHandler.END
            
            keyboard = [[InlineKeyboardButton(info['first_name'], callback_data=f"logs_{phone}")] 
                       for phone, info in accounts.items()]
            keyboard.append([InlineKeyboardButton("🔙 Back", callback_data='back')])
            
            await query.edit_message_text(
                "📊 *Select Account* to view join logs:",
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode='Markdown'
            )
            return ConversationHandler.END
        
        elif query.data.startswith('logs_'):
            phone = query.data.replace('logs_', '')
            logs = self.db.join_logs.get(phone, [])
            
            if not logs:
                await query.edit_message_text(f"📊 No join logs for {phone}")
                return ConversationHandler.END
            
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
            return ConversationHandler.END
        
        elif query.data == 'remove_account':
            accounts = self.db.get_accounts()
            if not accounts:
                await query.edit_message_text("❌ No accounts to remove.")
                return ConversationHandler.END
            
            keyboard = [[InlineKeyboardButton(info['first_name'], callback_data=f"remove_{phone}")] 
                       for phone, info in accounts.items()]
            keyboard.append([InlineKeyboardButton("🔙 Back", callback_data='back')])
            
            await query.edit_message_text(
                "🗑️ *Select Account* to remove:",
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode='Markdown'
            )
            return ConversationHandler.END
        
        elif query.data.startswith('remove_'):
            phone = query.data.replace('remove_', '')
            await self.account_manager.logout_account(phone)
            await query.edit_message_text(f"✅ Account {phone} has been removed.")
            return ConversationHandler.END
        
        elif query.data == 'back':
            # Go back to main menu
            keyboard = [
                [InlineKeyboardButton("➕ Add Account", callback_data='add_account')],
                [InlineKeyboardButton("📋 List Accounts", callback_data='list_accounts')],
                [InlineKeyboardButton("🔗 Join Groups", callback_data='join_groups')],
                [InlineKeyboardButton("📊 View Logs", callback_data='view_logs')],
                [InlineKeyboardButton("❌ Remove Account", callback_data='remove_account')]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await query.edit_message_text(
                "🤖 *Telegram Group Joiner Bot*\n\n"
                "Main Menu - Choose an option:",
                reply_markup=reply_markup,
                parse_mode='Markdown'
            )
            return ConversationHandler.END
        
        return ConversationHandler.END
    
    async def phone_number_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle phone number input"""
        phone = update.message.text.strip()
        logger.info(f"Received phone number: {phone} from user {update.effective_user.id}")
        
        # Basic phone number validation
        if not phone.startswith('+') or not phone[1:].replace(' ', '').isdigit():
            logger.warning(f"Invalid phone number format: {phone}")
            await update.message.reply_text(
                "❌ *Invalid phone number format*\n\n"
                "Please use international format with country code.\n"
                "Example: `+1234567890`\n\n"
                "Make sure:\n"
                "• Starts with +\n"
                "• Contains only numbers after +\n"
                "• No spaces or dashes\n\n"
                "Send /cancel to cancel.",
                parse_mode='Markdown'
            )
            return PHONE_NUMBER
        
        # Remove spaces if any
        phone = phone.replace(' ', '')
        logger.info(f"Validated phone number: {phone}")
        
        # Start login process
        result = await self.account_manager.login_account(phone, update, context)
        return result
    
    async def code_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle verification code input"""
        code = update.message.text.strip()
        logger.info(f"Received code from user {update.effective_user.id}")
        
        # Validate code
        if not code.isdigit():
            logger.warning(f"Invalid code format: {code}")
            await update.message.reply_text(
                "❌ *Invalid code*\n\n"
                "Please enter the numeric code you received.\n"
                "The code should contain only numbers.\n\n"
                "Send /cancel to cancel.",
                parse_mode='Markdown'
            )
            return LOGIN_CODE
        
        logger.info(f"Valid code format, verifying...")
        result = await self.account_manager.verify_code(code, update, context)
        return result
    
    async def password_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle 2FA password input"""
        password = update.message.text.strip()
        logger.info(f"Received 2FA password from user {update.effective_user.id}")
        
        if not password:
            logger.warning("Empty password received")
            await update.message.reply_text(
                "❌ *Invalid password*\n\n"
                "Please enter your 2FA password.\n"
                "Send /cancel to cancel.",
                parse_mode='Markdown'
            )
            return LOGIN_PASSWORD
        
        result = await self.account_manager.verify_password(password, update, context)
        return result
    
    async def handle_groups(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle group links input"""
        if not context.user_data.get('waiting_for_groups'):
            return ConversationHandler.END
        
        group_links = update.message.text.strip().split('\n')
        group_links = [link.strip() for link in group_links if link.strip()]
        logger.info(f"Received {len(group_links)} group links from user {update.effective_user.id}")
        
        # Validate links
        valid_links = []
        for link in group_links:
            if self.account_manager.extract_invite_hash(link):
                valid_links.append(link)
            else:
                logger.warning(f"Invalid link format: {link}")
                await update.message.reply_text(f"⚠️ Invalid link format (skipped): {link}")
        
        if not valid_links:
            await update.message.reply_text("❌ No valid group links found. Please send valid Telegram invite links.")
            return WAITING_GROUPS
        
        selected_accounts = context.user_data.get('selected_accounts', [])
        logger.info(f"Processing {len(valid_links)} groups for {len(selected_accounts)} accounts")
        
        progress_msg = await update.message.reply_text(
            f"🚀 *Starting join process...*\n\n"
            f"📊 {len(valid_links)} groups\n"
            f"👥 {len(selected_accounts)} accounts\n\n"
            f"⏳ Processing...",
            parse_mode='Markdown'
        )
        
        all_results = {}
        
        for idx, phone in enumerate(selected_accounts):
            await progress_msg.edit_text(
                f"🚀 *Joining groups*\n\n"
                f"📊 Processing account {idx+1}/{len(selected_accounts)}\n"
                f"👤 Account: `{phone}`\n\n"
                f"⏳ Please wait...",
                parse_mode='Markdown'
            )
            
            result = await self.account_manager.join_groups_for_account(phone, valid_links)
            all_results[phone] = result
        
        # Generate summary
        summary = "*📊 Join Summary*\n\n"
        for phone, result in all_results.items():
            if result['success']:
                success_count = sum(1 for r in result['results'] if r['status'] == 'success')
                invalid_count = sum(1 for r in result['results'] if r['status'] in ['invalid_link', 'invalid', 'expired'])
                summary += f"**{phone}:**\n"
                summary += f"   ✅ Success: {success_count}\n"
                summary += f"   ❌ Failed: {invalid_count}\n"
                summary += f"   📊 Total: {len(valid_links)}\n\n"
            else:
                summary += f"**{phone}:** ❌ Failed - {result['error']}\n\n"
        
        await progress_msg.edit_text(summary, parse_mode='Markdown')
        
        # Send detailed report for each account
        for phone, result in all_results.items():
            if result['success'] and result['results']:
                report = f"*📋 Detailed Report for {phone}:*\n\n"
                for r in result['results']:
                    status_icon = {
                        'success': '✅',
                        'invalid_link': '❌',
                        'expired': '⏰',
                        'already_member': '👥',
                        'error': '⚠️'
                    }.get(r['status'], '❓')
                    report += f"{status_icon} `{r['link']}`\n"
                    report += f"   {r['message']}\n\n"
                    
                    # Split if too long
                    if len(report) > 3900:
                        await update.message.reply_text(report, parse_mode='Markdown')
                        report = ""
                
                if report:
                    await update.message.reply_text(report, parse_mode='Markdown')
        
        context.user_data['waiting_for_groups'] = False
        context.user_data['selected_accounts'] = []
        return ConversationHandler.END
    
    async def cancel(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Cancel conversation"""
        logger.info(f"Cancel command from user {update.effective_user.id}")
        context.user_data.clear()
        await update.message.reply_text(
            "❌ Operation cancelled.\n\n"
            "Use /start to begin again."
        )
        return ConversationHandler.END

# ==================== MAIN ====================
async def main():
    # Validate configuration
    if BOT_TOKEN == "YOUR_BOT_TOKEN_HERE":
        print("\n" + "="*60)
        print("❌ ERROR: Please set your BOT_TOKEN!")
        print("Get it from @BotFather on Telegram")
        print("="*60 + "\n")
        return
    
    if API_ID == 123456 or API_HASH == "your_api_hash_here":
        print("\n" + "="*60)
        print("❌ ERROR: Please set your API_ID and API_HASH!")
        print("Get them from https://my.telegram.org")
        print("="*60 + "\n")
        return
    
    # Initialize bot
    telegram_bot = TelegramBot()
    
    # Create application
    application = Application.builder().token(BOT_TOKEN).build()
    
    # Create conversation handlers
    login_conv_handler = ConversationHandler(
        entry_points=[CallbackQueryHandler(telegram_bot.button_handler, pattern='^add_account$')],
        states={
            PHONE_NUMBER: [MessageHandler(filters.TEXT & ~filters.COMMAND, telegram_bot.phone_number_handler)],
            LOGIN_CODE: [MessageHandler(filters.TEXT & ~filters.COMMAND, telegram_bot.code_handler)],
            LOGIN_PASSWORD: [MessageHandler(filters.TEXT & ~filters.COMMAND, telegram_bot.password_handler)],
        },
        fallbacks=[CommandHandler("cancel", telegram_bot.cancel)],
        allow_reentry=True
    )
    
    groups_conv_handler = ConversationHandler(
        entry_points=[CallbackQueryHandler(telegram_bot.button_handler, pattern='^continue_to_groups$')],
        states={
            WAITING_GROUPS: [MessageHandler(filters.TEXT & ~filters.COMMAND, telegram_bot.handle_groups)],
        },
        fallbacks=[CommandHandler("cancel", telegram_bot.cancel)],
        allow_reentry=True
    )
    
    # Add handlers
    application.add_handler(CommandHandler("start", telegram_bot.start))
    application.add_handler(CallbackQueryHandler(telegram_bot.button_handler))
    application.add_handler(login_conv_handler)
    application.add_handler(groups_conv_handler)
    
    # Start bot
    print("\n" + "="*60)
    print("✅ Bot is starting...")
    print(f"📡 Bot Token: {BOT_TOKEN[:15]}...")
    print("💡 Press Ctrl+C to stop")
    print("="*60 + "\n")
    
    # Start the bot
    await application.initialize()
    await application.start()
    await application.updater.start_polling()
    
    print("✅ Bot is running! Check the logs above for any errors.")
    print("📱 Open Telegram and start your bot with /start\n")
    
    # Keep running
    try:
        await asyncio.Event().wait()
    except KeyboardInterrupt:
        print("\n" + "="*60)
        print("👋 Shutting down gracefully...")
        print("="*60 + "\n")
        await application.stop()

if __name__ == "__main__":
    asyncio
