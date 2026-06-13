# database.py
import json
import os
from typing import Dict, List, Optional
from datetime import datetime
import asyncio

class Database:
    def __init__(self, accounts_file: str, groups_file: str, queue_file: str):
        self.accounts_file = accounts_file
        self.groups_file = groups_file
        self.queue_file = queue_file
        self.lock = asyncio.Lock()
        
    async def load_json(self, file_path: str, default: dict = None) -> dict:
        """Load JSON file with lock"""
        async with self.lock:
            if os.path.exists(file_path):
                try:
                    with open(file_path, 'r', encoding='utf-8') as f:
                        return json.load(f)
                except:
                    return default or {}
            return default or {}
    
    async def save_json(self, file_path: str, data: dict):
        """Save JSON file with lock"""
        async with self.lock:
            with open(file_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=4, ensure_ascii=False)
    
    # Account methods
    async def get_accounts(self) -> dict:
        return await self.load_json(self.accounts_file, {})
    
    async def save_account(self, phone: str, account_data: dict):
        accounts = await self.get_accounts()
        accounts[phone] = account_data
        await self.save_json(self.accounts_file, accounts)
    
    async def delete_account(self, phone: str):
        accounts = await self.get_accounts()
        if phone in accounts:
            del accounts[phone]
            await self.save_json(self.accounts_file, accounts)
    
    async def update_account_status(self, phone: str, active: bool):
        accounts = await self.get_accounts()
        if phone in accounts:
            accounts[phone]['active'] = active
            await self.save_json(self.accounts_file, accounts)
    
    # Group methods
    async def get_groups(self) -> Dict[str, dict]:
        return await self.load_json(self.groups_file, {})
    
    async def add_group(self, group_id: str, group_data: dict):
        groups = await self.get_groups()
        groups[group_id] = group_data
        await self.save_json(self.groups_file, groups)
    
    async def remove_group(self, group_id: str):
        groups = await self.get_groups()
        if group_id in groups:
            del groups[group_id]
            await self.save_json(self.groups_file, groups)
    
    # Queue methods
    async def get_queue(self) -> dict:
        return await self.load_json(self.queue_file, {'queue': [], 'processing': False})
    
    async def add_to_queue(self, user_id: int, accounts: List[str], groups: List[str]):
        queue_data = await self.get_queue()
        queue_data['queue'].append({
            'user_id': user_id,
            'accounts': accounts,
            'groups': groups,
            'timestamp': datetime.now().isoformat(),
            'status': 'pending'
        })
        await self.save_json(self.queue_file, queue_data)
    
    async def get_next_queue_item(self):
        queue_data = await self.get_queue()
        if queue_data['queue'] and not queue_data.get('processing', False):
            queue_data['processing'] = True
            await self.save_json(self.queue_file, queue_data)
            return queue_data['queue'][0]
        return None
    
    async def complete_queue_item(self):
        queue_data = await self.get_queue()
        if queue_data['queue']:
            queue_data['queue'].pop(0)
        queue_data['processing'] = False
        await self.save_json(self.queue_file, queue_data)
    
    async def clear_queue(self):
        await self.save_json(self.queue_file, {'queue': [], 'processing': False})
