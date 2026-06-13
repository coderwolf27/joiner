# simple_bot.py
# A simplified working version

import asyncio
import logging
from pathlib import Path
from telethon import TelegramClient, errors
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, ConversationHandler, filters, ContextTypes

# Enable logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ==================== CONFIGURATION ====================
# IMPORTANT: You MUST change these values
BOT_TOKEN = "8165906774:AAFYUEtSFr69bUVwW4nhMEq549EIzN4vPmU"  # Get from @BotFather
API_ID = 29687194  # Get from https://my.telegram.org
API_HASH = "fb286056a72033e9870cacb170b31fcd"  # Get from https://my.telegram.org

# States
PHONE, CODE, PASSWORD = range(3)

# Store user data temporarily
user_sessions = {}

class SimpleBot:
    def __init__(self):
        self.clients = {}
        
    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Start command"""
        keyboard = [
            [InlineKeyboardButton("➕ Login Account", callback_data='login')],
            [InlineKeyboardButton("📋 List Accounts", callback_data='list')],
            [InlineKeyboardButton("🔗 Join Group", callback_data='join')]
        ]
        await update.message.reply_text(
            "🤖 *Telegram Group Joiner Bot*\n\n选择选项:",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode='Markdown'
        )
    
    async def button_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle button presses"""
        query = update.callback_query
        await query.answer()
        
        if query.data == 'login':
            await query.edit_message_text(
                "📱 *Login*\n\n"
                "Send your phone number with country code.\n"
                "Example: `+1234567890`\n\n"
                "Send /cancel to cancel.",
                parse_mode='Markdown'
            )
            return PHONE
            
        elif query.data == 'list':
            if not self.clients:
                await query.edit_message_text("No accounts logged in.")
            else:
                msg = "*Logged in accounts:*\n\n"
                for phone in self.clients.keys():
                    msg += f"• `{phone}`\n"
                await query.edit_message_text(msg, parse_mode='Markdown')
                
        elif query.data == 'join':
            if not self.clients:
                await query.edit_message_text("No accounts. Please login first.")
            else:
                keyboard = []
                for phone in self.clients.keys():
                    keyboard.append([InlineKeyboardButton(phone, callback_data=f"use_{phone}")])
                await query.edit_message_text(
                    "Select account to use:",
                    reply_markup=InlineKeyboardMarkup(keyboard)
                )
                
        elif query.data.startswith('use_'):
            phone = query.data.replace('use_', '')
            context.user_data['join_phone'] = phone
            await query.edit_message_text(
                "Send the group invite link to join.\n"
                "Example: https://t.me/joinchat/xxxxx\n\n"
                "Send /cancel to cancel."
            )
            return 99  # Special state for waiting for group link
            
        return ConversationHandler.END
    
    async def phone_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle phone number"""
        phone = update.message.text.strip()
        logger.info(f"Login attempt for: {phone}")
        
        # Store phone number
        context.user_data['phone'] = phone
        user_id = update.effective_user.id
        
        # Create client
        session_file = f"sessions/{phone.replace('+', '')}"
        client = TelegramClient(session_file, API_ID, API_HASH)
        
        try:
            await client.connect()
            logger.info(f"Connected for {phone}")
            
            # Send code
            await client.send_code_request(phone)
            logger.info(f"Code sent to {phone}")
            
            # Store client
            user_sessions[user_id] = client
            
            await update.message.reply_text(
                "✅ Verification code sent!\n"
                "Please check your Telegram app and send the code here:"
            )
            return CODE
            
        except errors.PhoneNumberInvalidError:
            await update.message.reply_text("❌ Invalid phone number. Try again with /start")
            return ConversationHandler.END
        except Exception as e:
            logger.error(f"Error: {e}")
            await update.message.reply_text(f"❌ Error: {str(e)}")
            return ConversationHandler.END
    
    async def code_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle verification code"""
        code = update.message.text.strip()
        user_id = update.effective_user.id
        phone = context.user_data.get('phone')
        
        client = user_sessions.get(user_id)
        if not client:
            await update.message.reply_text("Session expired. Use /start")
            return ConversationHandler.END
        
        try:
            await client.sign_in(phone, code)
            me = await client.get_me()
            
            # Store client
            self.clients[phone] = client
            
            await update.message.reply_text(
                f"✅ *Login Successful!*\n\n"
                f"Welcome {me.first_name}!\n"
                f"Phone: {phone}\n\n"
                f"Use /start to continue.",
                parse_mode='Markdown'
            )
            
            # Cleanup
            del user_sessions[user_id]
            return ConversationHandler.END
            
        except errors.SessionPasswordNeededError:
            await update.message.reply_text(
                "🔐 *2FA Required*\n\n"
                "Enter your 2FA password:",
                parse_mode='Markdown'
            )
            return PASSWORD
        except errors.PhoneCodeInvalidError:
            await update.message.reply_text("❌ Invalid code. Try again with /start")
            return ConversationHandler.END
        except Exception as e:
            logger.error(f"Code error: {e}")
            await update.message.reply_text(f"❌ Error: {str(e)}")
            return ConversationHandler.END
    
    async def password_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle 2FA password"""
        password = update.message.text.strip()
        user_id = update.effective_user.id
        phone = context.user_data.get('phone')
        
        client = user_sessions.get(user_id)
        if not client:
            await update.message.reply_text("Session expired. Use /start")
            return ConversationHandler.END
        
        try:
            await client.sign_in(password=password)
            me = await client.get_me()
            
            self.clients[phone] = client
            
            await update.message.reply_text(
                f"✅ *Login Successful!*\n\n"
                f"Welcome {me.first_name}!\n"
                f"Phone: {phone}\n\n"
                f"Use /start to continue.",
                parse_mode='Markdown'
            )
            
            del user_sessions[user_id]
            return ConversationHandler.END
            
        except Exception as e:
            await update.message.reply_text(f"❌ Wrong password: {str(e)}")
            return ConversationHandler.END
    
    async def group_link_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle group link for joining"""
        link = update.message.text.strip()
        phone = context.user_data.get('join_phone')
        
        if not phone or phone not in self.clients:
            await update.message.reply_text("Account not found. Use /start")
            return ConversationHandler.END
        
        client = self.clients[phone]
        
        # Extract invite hash
        import re
        match = re.search(r'joinchat/([a-zA-Z0-9_-]+)', link)
        if not match:
            await update.message.reply_text("❌ Invalid invite link format")
            return ConversationHandler.END
        
        invite_hash = match.group(1)
        
        try:
            from telethon.tl.functions.messages import ImportChatInviteRequest
            result = await client(ImportChatInviteRequest(invite_hash))
            
            if result.chats:
                chat = result.chats[0]
                await update.message.reply_text(
                    f"✅ Successfully joined {chat.title}!"
                )
            else:
                await update.message.reply_text("❌ Failed to join group")
                
        except errors.InviteHashExpiredError:
            await update.message.reply_text("❌ Invite link expired")
        except errors.UserAlreadyParticipantError:
            await update.message.reply_text("✅ Already a member of this group")
        except Exception as e:
            await update.message.reply_text(f"❌ Error: {str(e)}")
        
        return ConversationHandler.END
    
    async def cancel(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Cancel operation"""
        await update.message.reply_text("Cancelled. Use /start")
        return ConversationHandler.END

async def main():
    # Check configuration
    if BOT_TOKEN == "YOUR_BOT_TOKEN_HERE":
        print("\n" + "="*50)
        print("ERROR: Please edit the script and add your:")
        print("1. BOT_TOKEN - Get from @BotFather")
        print("2. API_ID - Get from https://my.telegram.org")
        print("3. API_HASH - Get from https://my.telegram.org")
        print("="*50 + "\n")
        return
    
    # Create sessions directory
    Path("sessions").mkdir(exist_ok=True)
    
    bot = SimpleBot()
    app = Application.builder().token(BOT_TOKEN).build()
    
    # Conversation handler for login
    conv_handler = ConversationHandler(
        entry_points=[CallbackQueryHandler(bot.button_callback, pattern='^login$')],
        states={
            PHONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, bot.phone_handler)],
            CODE: [MessageHandler(filters.TEXT & ~filters.COMMAND, bot.code_handler)],
            PASSWORD: [MessageHandler(filters.TEXT & ~filters.COMMAND, bot.password_handler)],
        },
        fallbacks=[CommandHandler("cancel", bot.cancel)]
    )
    
    # Handler for joining groups
    join_handler = ConversationHandler(
        entry_points=[CallbackQueryHandler(bot.button_callback, pattern='^join$')],
        states={
            99: [MessageHandler(filters.TEXT & ~filters.COMMAND, bot.group_link_handler)],
        },
        fallbacks=[CommandHandler("cancel", bot.cancel)]
    )
    
    app.add_handler(CommandHandler("start", bot.start))
    app.add_handler(CallbackQueryHandler(bot.button_callback))
    app.add_handler(conv_handler)
    app.add_handler(join_handler)
    
    print("\n" + "="*50)
    print("✅ Bot is starting...")
    print(f"Bot token: {BOT_TOKEN[:20]}...")
    print("="*50 + "\n")
    
    await app.initialize()
    await app.start()
    await app.updater.start_polling()
    
    print("✅ Bot is running! Send /start on Telegram\n")
    
    try:
        await asyncio.Event().wait()
    except KeyboardInterrupt:
        print("\nShutting down...")
        await app.stop()

if __name__ == "__main__":
    asyncio.run(main())
