# account_manager.py
import asyncio
import os
from typing import Dict, List, Optional
from datetime import datetime
from telethon import TelegramClient
from telethon.errors import (
    FloodWaitError, UserAlreadyParticipantError, 
    InviteHashInvalidError, InviteHashExpiredError,
    ChannelPrivateError
)
from config import Config
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class AccountManager:
    def __init__(self, db):
        self.db = db
        self.api_id = Config.API_ID
        self.api_hash = Config.API_HASH
        self.session_dir = Config.SESSION_DIR
        self.clients: Dict[str, TelegramClient] = {}
        self.otp_sessions: Dict[str, dict] = {}  # Store OTP waiting sessions
        
    async def start_login(self, phone: str, user_id: int) -> dict:
        """Start login process and return status"""
        try:
            client = TelegramClient(
                os.path.join(self.session_dir, phone),
                self.api_id,
                self.api_hash
            )
            await client.connect()
            
            if await client.is_user_authorized():
                # Already logged in
                me = await client.get_me()
                await self.db.save_account(phone, {
                    'user_id': me.id,
                    'username': me.username or me.first_name,
                    'phone': phone,
                    'active': True,
                    'added_by': user_id,
                    'added_date': datetime.now().isoformat()
                })
                self.clients[phone] = client
                return {'success': True, 'message': f'✅ Already logged in as {me.first_name}', 'username': me.username}
            
            # Send OTP
            await client.send_code_request(phone)
            self.otp_sessions[phone] = {
                'client': client,
                'user_id': user_id,
                'phone': phone,
                'timestamp': datetime.now()
            }
            
            return {'success': True, 'message': f'📱 OTP sent to {phone}. Please send the code using /verify {phone} <code>', 'need_otp': True}
            
        except Exception as e:
            logger.error(f"Login start error: {e}")
            return {'success': False, 'message': f'❌ Error: {str(e)}'}
    
    async def verify_otp(self, phone: str, code: str) -> dict:
        """Verify OTP and complete login"""
        if phone not in self.otp_sessions:
            return {'success': False, 'message': '❌ No pending login for this number. Start with /login first'}
        
        session = self.otp_sessions[phone]
        client = session['client']
        user_id = session['user_id']
        
        try:
            await client.sign_in(phone, code)
            me = await client.get_me()
            
            await self.db.save_account(phone, {
                'user_id': me.id,
                'username': me.username or me.first_name,
                'phone': phone,
                'active': True,
                'added_by': user_id,
                'added_date': datetime.now().isoformat()
            })
            
            self.clients[phone] = client
            del self.otp_sessions[phone]
            
            return {'success': True, 'message': f'✅ Successfully logged in as {me.first_name}', 'username': me.username}
            
        except Exception as e:
            if 'password' in str(e).lower():
                return {'success': False, 'message': '🔐 2FA enabled. Please use /login_2fa command', 'need_2fa': True, 'phone': phone}
            return {'success': False, 'message': f'❌ Invalid OTP: {str(e)}'}
    
    async def verify_2fa(self, phone: str, password: str) -> dict:
        """Verify 2FA password"""
        if phone not in self.otp_sessions:
            return {'success': False, 'message': '❌ No pending login session'}
        
        session = self.otp_sessions[phone]
        client = session['client']
        
        try:
            await client.sign_in(password=password)
            me = await client.get_me()
            
            await self.db.save_account(phone, {
                'user_id': me.id,
                'username': me.username or me.first_name,
                'phone': phone,
                'active': True,
                'added_by': session['user_id'],
                'added_date': datetime.now().isoformat()
            })
            
            self.clients[phone] = client
            del self.otp_sessions[phone]
            
            return {'success': True, 'message': f'✅ Successfully logged in as {me.first_name}'}
            
        except Exception as e:
            return {'success': False, 'message': f'❌ Invalid password: {str(e)}'}
    
    async def load_saved_sessions(self):
        """Load all saved sessions on bot startup"""
        accounts = await self.db.get_accounts()
        for phone, data in accounts.items():
            if data.get('active', True):
                try:
                    client = TelegramClient(
                        os.path.join(self.session_dir, phone),
                        self.api_id,
                        self.api_hash
                    )
                    await client.connect()
                    
                    if await client.is_user_authorized():
                        self.clients[phone] = client
                        logger.info(f"Loaded session for {phone}")
                    else:
                        # Session invalid, remove from accounts
                        await self.db.delete_account(phone)
                except Exception as e:
                    logger.error(f"Failed to load session for {phone}: {e}")
    
    async def get_active_accounts(self) -> Dict[str, dict]:
        """Get all active accounts"""
        accounts = await self.db.get_accounts()
        return {phone: data for phone, data in accounts.items() if data.get('active', True)}
    
    async def join_groups(self, account_phones: List[str], group_links: List[str], user_id: int) -> Dict:
        """Join groups using specified accounts"""
        results = {}
        
        for phone in account_phones:
            if phone not in self.clients:
                results[phone] = {'error': 'Account not connected'}
                continue
            
            client = self.clients[phone]
            account_results = []
            
            for group_link in group_links:
                result = await self._join_single_group(client, group_link, phone)
                account_results.append(result)
                await asyncio.sleep(2)  # Delay to avoid flood
            
            results[phone] = account_results
            await asyncio.sleep(3)  # Delay between accounts
        
        # Save results to log
        await self._save_join_log(user_id, results, group_links)
        return results
    
    async def _join_single_group(self, client: TelegramClient, group_link: str, phone: str) -> Dict:
        """Join a single group"""
        result = {
            'group': group_link,
            'status': 'pending',
            'message': ''
        }
        
        try:
            # Extract invite hash
            if 'joinchat/' in group_link:
                invite_hash = group_link.split('joinchat/')[-1]
            elif '+/' in group_link:
                invite_hash = group_link.split('+/')[-1]
            elif 't.me/' in group_link:
                invite_hash = group_link.split('t.me/')[-1]
                if 'joinchat/' in invite_hash:
                    invite_hash = invite_hash.split('joinchat/')[-1]
            else:
                invite_hash = group_link
            
            await client.join_chat(invite_hash)
            result['status'] = 'success'
            result['message'] = '✅ Joined successfully'
            
        except FloodWaitError as e:
            result['status'] = 'flood_wait'
            result['message'] = f'⏰ Flood wait: {e.seconds} seconds'
            
        except UserAlreadyParticipantError:
            result['status'] = 'already_member'
            result['message'] = 'ℹ️ Already a member'
            
        except (InviteHashInvalidError, ChannelPrivateError):
            result['status'] = 'invalid_link'
            result['message'] = '❌ Invalid invite link'
            
        except InviteHashExpiredError:
            result['status'] = 'expired_link'
            result['message'] = '⏰ Invite link expired'
            
        except Exception as e:
            result['status'] = 'error'
            result['message'] = f'⚠️ Error: {str(e)[:50]}'
        
        return result
    
    async def _save_join_log(self, user_id: int, results: Dict, groups: List[str]):
        """Save join results to log file"""
        log_file = os.path.join(Config.DATA_DIR, f'user_{user_id}_logs.txt')
        with open(log_file, 'a', encoding='utf-8') as f:
            f.write(f"\n{'='*60}\n")
            f.write(f"Join Results - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write(f"Groups: {', '.join(groups)}\n")
            f.write(f"{'='*60}\n")
            
            for phone, account_results in results.items():
                f.write(f"\nAccount: {phone}\n")
                f.write(f"{'-'*40}\n")
                if isinstance(account_results, list):
                    for result in account_results:
                        f.write(f"Group: {result['group']}\n")
                        f.write(f"Status: {result['status']}\n")
                        f.write(f"Message: {result['message']}\n\n")
                else:
                    f.write(f"Error: {account_results.get('error', 'Unknown error')}\n")
    
    async def logout_account(self, phone: str):
        """Logout and remove account"""
        if phone in self.clients:
            await self.clients[phone].disconnect()
            del self.clients[phone]
        
        await self.db.delete_account(phone)
        
        # Remove session file
        session_file = os.path.join(self.session_dir, f"{phone}.session")
        if os.path.exists(session_file):
            os.remove(session_file)
    
    async def disconnect_all(self):
        """Disconnect all clients"""
        for client in self.clients.values():
            await client.disconnect()
