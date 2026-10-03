import aiohttp
import backoff
import asyncio  # добавлено для обработки asyncio.TimeoutError
import logging
from telegram.error import NetworkError, TimedOut

logger = logging.getLogger(__name__)

NOTION_VERSION = "2022-06-28"

@backoff.on_exception(
    backoff.expo,
    (aiohttp.ClientError, asyncio.TimeoutError, NetworkError, TimedOut),  # добавили asyncio.TimeoutError
    max_tries=5
)
async def create_new_page(notion_token: str, database_id: str) -> str:
    headers = {
        "Authorization": f"Bearer {notion_token}",
        "Notion-Version": NOTION_VERSION,
        "Content-Type": "application/json"
    }
    data = {
        "parent": {"database_id": database_id},
        "properties": {}
    }
    # Увеличили таймаут до 60 секунд
    timeout = aiohttp.ClientTimeout(total=60)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.post(
            "https://api.notion.com/v1/pages",
            headers=headers,
            json=data
        ) as response:
            if response.status == 200:
                result = await response.json()
                return result["id"]
            else:
                logger.error(f"Failed to create new page: {response.status}")
                return None

@backoff.on_exception(
    backoff.expo,
    (aiohttp.ClientError, asyncio.TimeoutError, NetworkError, TimedOut),  # добавили asyncio.TimeoutError
    max_tries=5
)
async def get_notion_properties(notion_token: str, database_id: str) -> list:
    headers = {
        "Authorization": f"Bearer {notion_token}",
        "Notion-Version": NOTION_VERSION
    }
    timeout = aiohttp.ClientTimeout(total=60)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.get(
            f"https://api.notion.com/v1/databases/{database_id}",
            headers=headers
        ) as response:
            if response.status == 200:
                data = await response.json()
                return process_notion_properties(data)
            else:
                logger.error(f"Failed to get Notion properties: {response.status}")
                return []

def process_notion_properties(data: dict) -> list:
    try:
        properties = data.get('properties', {})
        supported = {'title', 'rich_text', 'number', 'select', 'multi_select', 'date', 'checkbox'}
        props_list = []
        for prop_name, prop_data in properties.items():
            prop_type = prop_data['type']
            if prop_type not in supported:
                continue
            options = prop_data.get(prop_type, {}).get('options', []) if prop_type in {'select', 'multi_select'} else []
            props_list.append({'name': prop_name, 'type': prop_type, 'options': options})
        return props_list
    except Exception as e:
        logger.error(f"Error processing Notion properties: {str(e)}")
        return []

@backoff.on_exception(
    backoff.expo,
    (aiohttp.ClientError, asyncio.TimeoutError, NetworkError, TimedOut),  # добавили asyncio.TimeoutError
    max_tries=5
)
async def update_notion_property(
    notion_token: str,
    page_id: str,
    property_name: str,
    property_type: str,
    value: str
) -> bool:
    headers = {
        "Authorization": f"Bearer {notion_token}",
        "Notion-Version": NOTION_VERSION,
        "Content-Type": "application/json"
    }
    property_data = create_property_data(property_type, value)
    if property_data is None:
        return False

    data = {
        "properties": {
            property_name: property_data
        }
    }

    timeout = aiohttp.ClientTimeout(total=60)  # увеличен таймаут до 60 секунд
    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.patch(
            f"https://api.notion.com/v1/pages/{page_id}",
            headers=headers,
            json=data
        ) as response:
            if response.status == 200:
                return True
            else:
                logger.error(f"Failed to update property: {response.status}")
                return False

def create_property_data(property_type: str, value: str) -> dict or None:
    try:
        if property_type == "title":
            return {"title": [{"text": {"content": str(value)}}]}
        elif property_type == "rich_text":
            return {"rich_text": [{"text": {"content": str(value)}}]}
        elif property_type == "number":
            return {"number": float(value)}
        elif property_type == "select":
            return {"select": {"name": str(value)}}
        elif property_type == "multi_select":
            values = [v.strip() for v in str(value).split(',')]
            return {"multi_select": [{"name": v} for v in values]}
        elif property_type == "date":
            return {"date": {"start": str(value)}}
        elif property_type == "checkbox":
            return {"checkbox": (value.lower() in ('true', 'yes', '1'))}
        else:
            return {"rich_text": [{"text": {"content": str(value)}}]}
    except Exception as e:
        logger.error(f"Error creating property data: {str(e)}")
        return None
