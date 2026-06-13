# bot_handler.py
import asyncio
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler, 
    MessageHandler, filters, ContextTypes
)
from telegram.constants import ParseMode
from config import Config
from account_manager import AccountManager
from database import Database
import re
from typing import List

class TelegramGroupJoinerBot:
    def __init__(self):
        self.db = Database(
            Config.ACCOUNTS_FILE,
            Config.GROUPS_FILE,
            Config.JOIN_QUEUE_FILE
        )
        self.account_manager = AccountManager(self.db)
        self.user_sessions = {}  # Store user temporary data
        
    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /start command"""
        user = update.effective_user
        welcome_text = f"""
🎉 *Welcome to Group Joiner Bot, {user.first_name}!* 🎉

I can help you automatically join Telegram groups using multiple accounts.

*What I can do:*
✅ Login multiple Telegram accounts (OTP or Session file)
✅ Add unlimited group links
✅ Auto-join groups with selected accounts
✅ Track successful/invalid/expired links
✅ Detailed logs for all joins

*Quick Start:*
1️⃣ Use /login to add your first account
2️⃣ Use /addgroups to add group links
3️⃣ Use /joingroups to start joining

*Commands:*
/login - Add new Telegram account
/myaccounts - View all logged-in accounts
/logout - Remove an account
/addgroups - Add group links
/mygroups - View added groups
/removegroup - Remove a group link
/joingroups - Start joining process
/status - Check join status
/logs - View join logs
/help - Show this help message
        """
        await update.message.reply_text(welcome_text, parse_mode=ParseMode.MARKDOWN)
    
    async def help_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /help command"""
        help_text = """
*📚 Available Commands*

*Account Management:*
/login - Add a new Telegram account
/myaccounts - List all your accounts
/logout - Remove an account

*Group Management:*
/addgroups - Add group links (send as list or file)
/mygroups - View your group links
/removegroup - Remove a specific group

*Joining:*
/joingroups - Start auto-join process
/status - Check join status
/cancel - Cancel ongoing operation
/logs - View your join history

*How to use:*
1. First add accounts using /login
2. Add group links using /addgroups
3. Use /joingroups and select accounts
4. Bot will process and show results

*Group Link Formats:*
• https://t.me/joinchat/xxxxx
• https://t.me/username
• https://t.me/+xxxxx
        """
        await update.message.reply_text(help_text, parse_mode=ParseMode.MARKDOWN)
    
    async def login_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Start login process"""
        user_id = update.effective_user.id
        
        # Ask for phone number
        self.user_sessions[user_id] = {'action': 'waiting_phone'}
        await update.message.reply_text(
            "📱 *Login to Telegram Account*\n\n"
            "Please send your phone number with country code.\n"
            "Example: `+1234567890`\n\n"
            "Type /cancel to cancel.",
            parse_mode=ParseMode.MARKDOWN
        )
    
    async def login_2fa(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle 2FA login"""
        args = context.args
        if not args:
            await update.message.reply_text(
                "Usage: `/login_2fa <password>`\n"
                "Example: `/login_2fa mypassword`",
                parse_mode=ParseMode.MARKDOWN
            )
            return
        
        password = ' '.join(args)
        user_id = update.effective_user.id
        
        if user_id not in self.user_sessions or '2fa_phone' not in self.user_sessions[user_id]:
            await update.message.reply_text("❌ No pending 2FA request. Please start with /login first.")
            return
        
        phone = self.user_sessions[user_id]['2fa_phone']
        result = await self.account_manager.verify_2fa(phone, password)
        
        if result['success']:
            await update.message.reply_text(f"✅ {result['message']}\n\nUse /myaccounts to view your accounts.")
            del self.user_sessions[user_id]
        else:
            await update.message.reply_text(f"❌ {result['message']}\n\nTry again with /login_2fa <password>")
    
    async def handle_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle user messages"""
        user_id = update.effective_user.id
        text = update.message.text.strip()
        
        # Check if user is in a session
        if user_id in self.user_sessions:
            action = self.user_sessions[user_id].get('action')
            
            if action == 'waiting_phone':
                # Validate phone number
                if not re.match(r'^\+?[0-9]{10,15}$', text):
                    await update.message.reply_text("❌ Invalid phone number. Please send a valid number with country code.\nExample: `+1234567890`", parse_mode=ParseMode.MARKDOWN)
                    return
                
                result = await self.account_manager.start_login(text, user_id)
                
                if result.get('need_otp'):
                    self.user_sessions[user_id] = {
                        'action': 'waiting_otp',
                        'phone': text
                    }
                    await update.message.reply_text(
                        f"📱 {result['message']}\n\n"
                        "Send the OTP code using:\n`/verify <code>`\n\n"
                        "Example: `/verify 12345`",
                        parse_mode=ParseMode.MARKDOWN
                    )
                elif result['success']:
                    await update.message.reply_text(f"✅ {result['message']}\n\nUse /myaccounts to view your accounts.")
                    del self.user_sessions[user_id]
                else:
                    await update.message.reply_text(f"❌ {result['message']}")
                    del self.user_sessions[user_id]
            
            elif action == 'waiting_groups':
                # Process group links
                links = [line.strip() for line in text.split('\n') if line.strip()]
                valid_links = []
                invalid_links = []
                
                for link in links:
                    if 't.me/' in link or 'telegram.me/' in link:
                        valid_links.append(link)
                    else:
                        invalid_links.append(link)
                
                if valid_links:
                    # Save groups to database
                    for link in valid_links:
                        await self.db.add_group(link, {
                            'link': link,
                            'added_by': user_id,
                            'added_date': str(update.message.date),
                            'active': True
                        })
                    
                    await update.message.reply_text(
                        f"✅ Added {len(valid_links)} group(s) successfully!\n\n"
                        f"Use /mygroups to view all groups.\n"
                        f"Use /joingroups to start joining."
                    )
                
                if invalid_links:
                    await update.message.reply_text(
                        f"⚠️ {len(invalid_links)} invalid link(s) skipped:\n" + 
                        '\n'.join(invalid_links[:5])
                    )
                
                del self.user_sessions[user_id]
    
    async def verify_otp(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle OTP verification"""
        args = context.args
        if not args:
            await update.message.reply_text(
                "Usage: `/verify <code>`\n"
                "Example: `/verify 12345`",
                parse_mode=ParseMode.MARKDOWN
            )
            return
        
        code = args[0]
        user_id = update.effective_user.id
        
        if user_id not in self.user_sessions or 'phone' not in self.user_sessions[user_id]:
            await update.message.reply_text("❌ No pending login. Please start with /login first.")
            return
        
        phone = self.user_sessions[user_id]['phone']
        result = await self.account_manager.verify_otp(phone, code)
        
        if result.get('need_2fa'):
            self.user_sessions[user_id]['2fa_phone'] = phone
            await update.message.reply_text(
                "🔐 *2FA Authentication Required*\n\n"
                "Please send your 2FA password using:\n"
                "`/login_2fa <password>`\n\n"
                "Example: `/login_2fa mypassword`",
                parse_mode=ParseMode.MARKDOWN
            )
        elif result['success']:
            await update.message.reply_text(f"✅ {result['message']}\n\nUse /myaccounts to view your accounts.")
            del self.user_sessions[user_id]
        else:
            await update.message.reply_text(f"❌ {result['message']}\n\nTry again with /login")
    
    async def my_accounts(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show all logged-in accounts"""
        accounts = await self.account_manager.get_active_accounts()
        
        if not accounts:
            await update.message.reply_text(
                "❌ No accounts found.\n\n"
                "Add your first account with /login"
            )
            return
        
        account_list = "*📱 Your Accounts:*\n\n"
        for i, (phone, data) in enumerate(accounts.items(), 1):
            status = "✅ Active" if data.get('active', True) else "❌ Inactive"
            account_list += f"{i}. *{data.get('username', 'Unknown')}*\n"
            account_list += f"   📞 `{phone}`\n"
            account_list += f"   Status: {status}\n\n"
        
        account_list += "\nUse /logout <phone> to remove an account."
        
        await update.message.reply_text(account_list, parse_mode=ParseMode.MARKDOWN)
    
    async def logout_account(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Logout an account"""
        args = context.args
        if not args:
            await update.message.reply_text(
                "Usage: `/logout <phone>`\n"
                "Example: `/logout +1234567890`\n\n"
                "Use /myaccounts to see your accounts.",
                parse_mode=ParseMode.MARKDOWN
            )
            return
        
        phone = args[0]
        accounts = await self.account_manager.get_active_accounts()
        
        if phone not in accounts:
            await update.message.reply_text(f"❌ Account {phone} not found.")
            return
        
        await self.account_manager.logout_account(phone)
        await update.message.reply_text(f"✅ Successfully logged out account: {phone}")
    
    async def add_groups(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Add group links"""
        user_id = update.effective_user.id
        
        # Check if there's a document
        if update.message.document:
            # Handle file upload
            file = await update.message.document.get_file()
            file_content = await file.download_as_bytearray()
            links = file_content.decode('utf-8').split('\n')
            
            valid_count = 0
            for link in links:
                link = link.strip()
                if link and ('t.me/' in link or 'telegram.me/' in link):
                    await self.db.add_group(link, {
                        'link': link,
                        'added_by': user_id,
                        'added_date': str(update.message.date),
                        'active': True
                    })
                    valid_count += 1
            
            await update.message.reply_text(
                f"✅ Added {valid_count} groups from file!\n\n"
                f"Use /mygroups to view all groups.\n"
                f"Use /joingroups to start joining."
            )
        else:
            # Ask user to send links
            self.user_sessions[user_id] = {'action': 'waiting_groups'}
            await update.message.reply_text(
                "📝 *Add Group Links*\n\n"
                "Please send your group links (one per line).\n\n"
                "Supported formats:\n"
                "• `https://t.me/joinchat/xxxxx`\n"
                "• `https://t.me/username`\n"
                "• `https://t.me/+xxxxx`\n\n"
                "You can also send a `.txt` file with links.\n\n"
                "Type /cancel to cancel.",
                parse_mode=ParseMode.MARKDOWN
            )
    
    async def my_groups(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show all added groups"""
        groups = await self.db.get_groups()
        
        if not groups:
            await update.message.reply_text(
                "❌ No groups added.\n\n"
                "Add groups with /addgroups"
            )
            return
        
        group_list = "*📋 Your Groups:*\n\n"
        for i, (group_id, data) in enumerate(list(groups.items())[:20], 1):
            group_list += f"{i}. `{data['link'][:50]}`\n"
        
        if len(groups) > 20:
            group_list += f"\n... and {len(groups) - 20} more groups."
        
        group_list += f"\n\nTotal: {len(groups)} groups"
        group_list += "\n\nUse /removegroup to remove a group."
        
        await update.message.reply_text(group_list, parse_mode=ParseMode.MARKDOWN)
    
    async def remove_group(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Remove a group link"""
        args = context.args
        if not args:
            await update.message.reply_text(
                "Usage: `/removegroup <link or number>`\n"
                "Example: `/removegroup https://t.me/joinchat/xxx`\n"
                "Or: `/removegroup 1` (from /mygroups list)",
                parse_mode=ParseMode.MARKDOWN
            )
            return
        
        groups = await self.db.get_groups()
        
        if args[0].isdigit():
            # Remove by index
            index = int(args[0]) - 1
            group_ids = list(groups.keys())
            if 0 <= index < len(group_ids):
                group_id = group_ids[index]
                await self.db.remove_group(group_id)
                await update.message.reply_text("✅ Group removed successfully!")
            else:
                await update.message.reply_text("❌ Invalid group number.")
        else:
            # Remove by link
            link = ' '.join(args)
            for group_id, data in groups.items():
                if data['link'] == link:
                    await self.db.remove_group(group_id)
                    await update.message.reply_text("✅ Group removed successfully!")
                    return
            await update.message.reply_text("❌ Group not found.")
    
    async def join_groups_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Start group joining process with account selection"""
        user_id = update.effective_user.id
        
        # Get accounts and groups
        accounts = await self.account_manager.get_active_accounts()
        groups = await self.db.get_groups()
        
        if not accounts:
            await update.message.reply_text(
                "❌ No accounts found.\n\n"
                "Add accounts with /login first."
            )
            return
        
        if not groups:
            await update.message.reply_text(
                "❌ No groups found.\n\n"
                "Add groups with /addgroups first."
            )
            return
        
        # Create inline keyboard for account selection
        keyboard = []
        for phone, data in accounts.items():
            keyboard.append([InlineKeyboardButton(
                f"✅ {data['username']} ({phone})",
                callback_data=f"select_acc_{phone}"
            )])
        
        keyboard.append([InlineKeyboardButton("📌 Select All", callback_data="select_all")])
        keyboard.append([InlineKeyboardButton("🚀 Start Joining", callback_data="start_join")])
        keyboard.append([InlineKeyboardButton("❌ Cancel", callback_data="cancel_join")])
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        # Store selection in context
        context.user_data['selected_accounts'] = []
        context.user_data['groups'] = list(groups.keys())
        
        await update.message.reply_text(
            f"*🎯 Select Accounts to Join*\n\n"
            f"Found {len(accounts)} account(s) and {len(groups)} group(s).\n\n"
            "Click on accounts to select them, then press 'Start Joining'.",
            reply_markup=reply_markup,
            parse_mode=ParseMode.MARKDOWN
        )
    
    async def button_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle button callbacks"""
        query = update.callback_query
        await query.answer()
        
        data = query.data
        
        if data.startswith("select_acc_"):
            phone = data.replace("select_acc_", "")
            if phone in context.user_data['selected_accounts']:
                context.user_data['selected_accounts'].remove(phone)
                await query.edit_message_text(
                    f"❌ Deselected: {phone}\n\nSelected: {len(context.user_data['selected_accounts'])} accounts",
                    reply_markup=query.message.reply_markup
                )
            else:
                context.user_data['selected_accounts'].append(phone)
                await query.edit_message_text(
                    f"✅ Selected: {phone}\n\nSelected: {len(context.user_data['selected_accounts'])} accounts",
                    reply_markup=query.message.reply_markup
                )
        
        elif data == "select_all":
            accounts = await self.account_manager.get_active_accounts()
            context.user_data['selected_accounts'] = list(accounts.keys())
            await query.edit_message_text(
                f"✅ Selected all {len(accounts)} accounts!\n\nPress 'Start Joining' to begin.",
                reply_markup=query.message.reply_markup
            )
        
        elif data == "start_join":
            if not context.user_data.get('selected_accounts'):
                await query.edit_message_text(
                    "❌ No accounts selected!\n\nPlease select at least one account to continue."
                )
                return
            
            await query.edit_message_text(
                f"🚀 *Starting join process...*\n\n"
                f"📱 Accounts: {len(context.user_data['selected_accounts'])}\n"
                f"📋 Groups: {len(context.user_data['groups'])}\n\n"
                f"Processing... This may take a few minutes.",
                parse_mode=ParseMode.MARKDOWN
            )
            
            # Process the joins
            results = await self.account_manager.join_groups(
                context.user_data['selected_accounts'],
                context.user_data['groups'],
                update.effective_user.id
            )
            
            # Format results
            result_text = "*📊 Join Results*\n\n"
            success_count = 0
            fail_count = 0
            
            for phone, account_results in results.items():
                result_text += f"*Account: {phone}*\n"
                for result in account_results:
                    if result['status'] == 'success':
                        success_count += 1
                        result_text += f"✅ {result['group'][:30]}...\n"
                    else:
                        fail_count += 1
                        result_text += f"❌ {result['group'][:30]}... - {result['message'][:30]}\n"
                result_text += "\n"
            
            result_text += f"\n*Summary:*\n✅ Success: {success_count}\n❌ Failed: {fail_count}"
            result_text += f"\n\nUse /logs to see detailed logs."
            
            await query.message.reply_text(result_text, parse_mode=ParseMode.MARKDOWN)
            context.user_data.clear()
        
        elif data == "cancel_join":
            await query.edit_message_text("❌ Operation cancelled.")
            context.user_data.clear()
    
    async def status_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Check bot status"""
        accounts = await self.account_manager.get_active_accounts()
        groups = await self.db.get_groups()
        queue = await self.db.get_queue()
        
        status_text = f"""
*📊 Bot Status*

*Accounts:* {len(accounts)} active
*Groups:* {len(groups)} added
*Queue:* {len(queue['queue'])} pending

*System Status:* 🟢 Online
*Connected Accounts:* {len(self.account_manager.clients)}/{len(accounts)}

Use /joingroups to start joining process.
        """
        await update.message.reply_text(status_text, parse_mode=ParseMode.MARKDOWN)
    
    async def logs_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show join logs"""
        user_id = update.effective_user.id
        log_file = f'data/user_{user_id}_logs.txt'
        
        try:
            with open(log_file, 'r', encoding='utf-8') as f:
                logs = f.read()
                if logs:
                    # Send last 3000 characters
                    if len(logs) > 3000:
                        logs = logs[-3000:]
                    await update.message.reply_text(
                        f"*📜 Recent Join Logs*\n\n```\n{logs}\n```",
                        parse_mode=ParseMode.MARKDOWN
                    )
                else:
                    await update.message.reply_text("No logs found yet. Start joining groups to generate logs.")
        except:
            await update.message.reply_text("No logs found yet. Start joining groups to generate logs.")
    
    async def cancel_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Cancel current operation"""
        user_id = update.effective_user.id
        if user_id in self.user_sessions:
            del self.user_sessions[user_id]
            await update.message.reply_text("✅ Operation cancelled.")
        else:
            await update.message.reply_text("No active operation to cancel.")
    
    async def error_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle errors"""
        logger.error(f"Update {update} caused error {context.error}")
        if update and update.effective_message:
            await update.effective_message.reply_text(
                "⚠️ An error occurred. Please try again later.\n"
                "If problem persists, contact support."
            )
    
    async def run(self):
        """Start the bot"""
        # Load saved sessions
        await self.account_manager.load_saved_sessions()
        
        # Create application
        application = Application.builder().token(Config.BOT_TOKEN).build()
        
        # Add handlers
        application.add_handler(CommandHandler("start", self.start))
        application.add_handler(CommandHandler("help", self.help_command))
        application.add_handler(CommandHandler("login", self.login_start))
        application.add_handler(CommandHandler("login_2fa", self.login_2fa))
        application.add_handler(CommandHandler("verify", self.verify_otp))
        application.add_handler(CommandHandler("myaccounts", self.my_accounts))
        application.add_handler(CommandHandler("logout", self.logout_account))
        application.add_handler(CommandHandler("addgroups", self.add_groups))
        application.add_handler(CommandHandler("mygroups", self.my_groups))
        application.add_handler(CommandHandler("removegroup", self.remove_group))
        application.add_handler(CommandHandler("joingroups", self.join_groups_start))
        application.add_handler(CommandHandler("status", self.status_command))
        application.add_handler(CommandHandler("logs", self.logs_command))
        application.add_handler(CommandHandler("cancel", self.cancel_command))
        
        # Handle messages
        application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_message))
        application.add_handler(MessageHandler(filters.Document.ALL, self.add_groups))
        
        # Handle callbacks
        application.add_handler(CallbackQueryHandler(self.button_callback))
        
        # Error handler
        application.add_error_handler(self.error_handler)
        
        # Start bot
        print("🤖 Bot is running...")
        await application.initialize()
        await application.start()
        await application.updater.start_polling()
        
        # Keep running
        await asyncio.Event().wait()

async def main():
    bot = TelegramGroupJoinerBot()
    await bot.run()

if __name__ == "__main__":
    asyncio.run(main())
