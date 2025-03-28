import os
import time
import xml.etree.ElementTree as ET
from loguru import logger
import tomllib
from WechatAPI import WechatAPIClient
from utils.decorators import *
from utils.plugin_base import PluginBase

class AntiRevoke(PluginBase):
    """微信消息防撤回插件"""
    
    description = "监控群聊和私聊消息撤回并通知管理员"
    author = "Grok"
    version = "2.2.0"
    
    _instance = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(AntiRevoke, cls).__new__(cls)
        return cls._instance
    
    def __init__(self):
        if hasattr(self, '_initialized'):
            return
        super().__init__()
        
        try:
            config_path = os.path.join(os.path.dirname(__file__), "config.toml")
            logger.info(f"加载配置文件: {config_path}")
            with open(config_path, "rb") as f:
                config = tomllib.load(f)
            
            plugin_config = config.get("AntiRevoke", {})
            self.enable = plugin_config.get("enable", False)
            self.admins = plugin_config.get("admins", [])
            self.cache_timeout = plugin_config.get("cache_timeout", 300)
            
            self.message_cache = {}
            
            if not self.admins:
                logger.error("未配置管理员列表，将无法发送通知")
            else:
                logger.info(f"管理员列表: {self.admins}")
            
            logger.info(f"插件初始化成功，实例ID: {id(self)}")
            self._initialized = True
            
        except Exception as e:
            logger.error(f"插件初始化失败: {str(e)}")
            self.enable = False
    
    async def on_start(self, bot: WechatAPIClient):
        """插件启动时执行，测试发送功能"""
        logger.info("插件启动，测试发送功能")
        for admin in self.admins:
            try:
                await bot.send_text_message(admin, "AntiRevoke 插件启动测试消息")
                logger.info(f"成功发送测试消息给 {admin}")
            except Exception as e:
                logger.error(f"发送测试消息给 {admin} 失败: {str(e)}")
    
    @on_text_message(priority=10)
    async def cache_text_message(self, bot: WechatAPIClient, message: dict) -> bool:
        """缓存文本消息"""
        logger.debug(f"收到文本消息: {message}")
        if not self.enable:
            logger.info("插件未启用，跳过缓存")
            return True
        
        new_msg_id = str(message.get("NewMsgId", ""))
        if not new_msg_id:
            logger.warning("消息缺少new_msg_id，跳过缓存")
            return True
        
        from_wxid = message.get("FromWxid", "")
        sender_wxid = message.get("SenderWxid", "")
        content = message.get("Content", "").strip()
        is_group = message.get("IsGroup", False)
        
        sender_nickname = self._extract_nickname(message, sender_wxid)
        
        self._cache_message(new_msg_id, content, sender_wxid, from_wxid, is_group, sender_nickname)
        return True
    
    @on_image_message(priority=10)
    async def cache_image_message(self, bot: WechatAPIClient, message: dict) -> bool:
        """缓存图片消息"""
        logger.debug(f"收到图片消息: {message}")
        if not self.enable:
            logger.info("插件未启用，跳过缓存")
            return True
        
        new_msg_id = str(message.get("NewMsgId", ""))
        if not new_msg_id:
            logger.warning("消息缺少new_msg_id，跳过缓存")
            return True
        
        from_wxid = message.get("FromWxid", "")
        sender_wxid = message.get("SenderWxid", "")
        is_group = message.get("IsGroup", False)
        
        sender_nickname = self._extract_nickname(message, sender_wxid)
        
        self._cache_message(new_msg_id, "[图片]", sender_wxid, from_wxid, is_group, sender_nickname)
        return True
    
    @on_file_message(priority=10)
    async def cache_file_message(self, bot: WechatAPIClient, message: dict) -> bool:
        """缓存文件消息"""
        logger.debug(f"收到文件消息: {message}")
        if not self.enable:
            logger.info("插件未启用，跳过缓存")
            return True
        
        new_msg_id = str(message.get("NewMsgId", ""))
        if not new_msg_id:
            logger.warning("消息缺少new_msg_id，跳过缓存")
            return True
        
        from_wxid = message.get("FromWxid", "")
        sender_wxid = message.get("SenderWxid", "")
        is_group = message.get("IsGroup", False)
        file_info = message.get("FileInfo", {})
        file_name = file_info.get("FileName", "[文件]")
        
        sender_nickname = self._extract_nickname(message, sender_wxid)
        
        self._cache_message(new_msg_id, f"[文件: {file_name}]", sender_wxid, from_wxid, is_group, sender_nickname)
        return True
    
    @on_system_message(priority=1)
    async def handle_revoke(self, bot: WechatAPIClient, message: dict) -> bool:
        """处理消息撤回事件"""
        logger.info(f"收到系统消息，处理撤回事件，实例ID: {id(self)}")
        
        if not self.enable:
            logger.info("插件未启用，跳过处理")
            return True
        
        content = message.get("Content", "")
        if "revokemsg" not in content:
            logger.debug("非撤回消息，跳过")
            return True
        
        try:
            root = ET.fromstring(content)
            revoke_msg = root.find(".//revokemsg")
            if revoke_msg is None:
                logger.error("未找到revokemsg节点")
                return True
            
            old_msg_id = revoke_msg.findtext("msgid")
            new_msg_id = revoke_msg.findtext("newmsgid")
            replace_msg = revoke_msg.findtext("replacemsg", "")
            
            logger.info(f"撤回消息详情: old_msg_id={old_msg_id}, new_msg_id={new_msg_id}")
            
            cached_msg = self.message_cache.get(new_msg_id)
            
            if not cached_msg:
                logger.error(f"未找到消息缓存: new_msg_id={new_msg_id}")
                return True
            
            logger.info(f"找到缓存消息: {cached_msg}")
            
            sender_wxid = cached_msg["sender"]
            chat_id = cached_msg["chat_id"]
            content = cached_msg["content"]
            is_group = cached_msg["is_group"]
            sender_nickname = cached_msg.get("sender_nickname", sender_wxid)
            
            if not sender_nickname and replace_msg:
                sender_nickname = self._extract_nickname_from_replacemsg(replace_msg)
            if not sender_nickname:
                sender_nickname = sender_wxid
            
            chat_name = chat_id
            notify_msg = f"{chat_name}群{sender_nickname}（{sender_wxid}）撤回了消息：{content}" if is_group else f"{sender_nickname}（{sender_wxid}）撤回了消息：{content}"
            
            logger.info(f"通知消息: {notify_msg}")
            
            if not self.admins:
                logger.error("管理员列表为空，无法发送通知")
                return True
            
            for admin in self.admins:
                try:
                    logger.info(f"发送通知给 {admin}")
                    await bot.send_text_message(admin, notify_msg)
                    logger.info(f"成功通知 {admin}")
                except Exception as e:
                    logger.error(f"通知 {admin} 失败: {str(e)}")
            
            if new_msg_id in self.message_cache:
                del self.message_cache[new_msg_id]
            
        except Exception as e:
            logger.error(f"处理撤回失败: {str(e)}")
        
        return True
    
    @on_text_message(priority=1)
    async def handle_test_command(self, bot: WechatAPIClient, message: dict) -> bool:
        """手动测试命令：发送 'test_revoke' 触发通知"""
        content = message.get("Content", "").strip()
        if content.lower() != "test_revoke":
            return True
        
        logger.info("收到测试命令：test_revoke")
        for admin in self.admins:
            try:
                await bot.send_text_message(admin, "AntiRevoke 插件测试消息")
                logger.info(f"成功发送测试消息给 {admin}")
            except Exception as e:
                logger.error(f"发送测试消息给 {admin} 失败: {str(e)}")
        
        return True
    
    def _cache_message(self, new_msg_id: str, content: str, sender: str, chat_id: str, is_group: bool, sender_nickname: str):
        """缓存消息"""
        self.message_cache[new_msg_id] = {
            "content": content,
            "sender": sender,
            "chat_id": chat_id,
            "is_group": is_group,
            "sender_nickname": sender_nickname,
            "timestamp": time.time()
        }
        logger.debug(f"缓存消息: new_msg_id={new_msg_id}, content={content}")
    
    def _extract_nickname(self, message: dict, default_wxid: str) -> str:
        """提取昵称"""
        msg_source = message.get("MsgSource", "")
        if "<msgsource>" in msg_source:
            try:
                root = ET.fromstring(msg_source)
                nick = root.find(".//nick")
                if nick is not None and nick.text:
                    return nick.text
            except:
                pass
        return default_wxid
    
    def _extract_nickname_from_replacemsg(self, replacemsg: str) -> str:
        """从replacemsg提取昵称"""
        if not replacemsg:
            return ""
        start = replacemsg.find("「")
        end = replacemsg.find("」")
        if start != -1 and end != -1 and start < end:
            return replacemsg[start + 1:end]
        return ""

plugin = AntiRevoke()
