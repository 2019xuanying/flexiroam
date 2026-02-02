import requests
import json
import time
from typing import Dict, Optional, Any

class FlexiroamAuth:
    """
    FlexiRoam 业务流程自动化处理类
    负责处理登录、OTP 请求、个人资料管理及会话维持
    """
    
    # 后端 API 基础地址
    BASE_API_URL = "https://prod-enduserservices.flexiroam.com/api"
    # 前端地址 (用于 Referer)
    ORIGIN_URL = "https://www.flexiroam.com"
    
    # 这是一个长期有效的 Client Token (Type: Client)，用于未登录状态下的公共接口调用
    CLIENT_BEARER_TOKEN = (
        "eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9.eyJjbGllbnRfaWQiOjQsImZpcnN0X25hbWUiOiJUcmF2ZWwiLC"
        "JsYXN0X25hbWUiOiJBcHAiLCJlbWFpbCI6InRyYXZlbGFwcEBmbGV4aXJvYW0uY29tIiwidHlwZSI6IkNsaWVud"
        "CIsImFjY2Vzc190eXBlIjoiQXBwIiwidXNlcl9hY2NvdW50X2lkIjo2LCJ1c2VyX3JvbGUiOiJWaWV3ZXIiLCJw"
        "ZXJtaXNzaW9uIjpbXSwiZXhwaXJlIjoxODc5NjcwMjYwfQ.-RtM_zNG-zBsD_S2oOEyy4uSbqR7wReAI92gp9uh-0Y"
    )

    def __init__(self):
        self.session = requests.Session()
        self.user_token: Optional[str] = None # 用于存储登录后的 User Token
        self._init_headers()

    def _init_headers(self):
        """
        初始化通用的浏览器 Header，模拟真实用户指纹
        """
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/144.0.0.0 Safari/537.36",
            "Accept": "*/*",
            "Accept-Language": "zh-CN,zh;q=0.9,en-US;q=0.8,en;q=0.7,zh-TW;q=0.6",
            "Sec-Ch-Ua": '"Not(A:Brand";v="8", "Chromium";v="144", "Google Chrome";v="144"',
            "Sec-Ch-Ua-Mobile": "?0",
            "Sec-Ch-Ua-Platform": '"Windows"',
            "Sec-Fetch-Dest": "empty",
            "Sec-Fetch-Mode": "cors",
            "Sec-Fetch-Site": "same-site",
            "Priority": "u=1, i",
            "Origin": self.ORIGIN_URL,
            "Referer": f"{self.ORIGIN_URL}/en-us/cart",
        })

    def _get_auth_header(self) -> Dict[str, str]:
        """
        动态获取 Authorization Header。
        如果有 User Token 则优先使用，否则使用 Client Token。
        """
        token = self.user_token if self.user_token else self.CLIENT_BEARER_TOKEN
        return {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Lang": "en-us"
        }

    def request_login_otp(self, email: str) -> Dict[str, Any]:
        """
        步骤 1: 请求向邮箱发送登录验证码
        """
        url = f"{self.BASE_API_URL}/loginwithemail/request/create"
        headers = self._get_auth_header()
        
        payload = {"email": email}

        print(f"[*] 步骤1: 正在请求 OTP 发送到: {email} ...")
        
        try:
            response = self.session.post(url, headers=headers, json=payload, timeout=10)
            response.raise_for_status()
            data = response.json()
            print(f"[+] OTP 请求成功! 状态码: {response.status_code}")
            return data
        except Exception as e:
            print(f"[-] OTP 请求失败: {e}")
            raise

    def verify_login_otp(self, email: str, otp_code: str) -> Optional[str]:
        """
        步骤 2: 提交验证码并获取 User Token
        """
        url = f"{self.BASE_API_URL}/loginwithemail/code/verify"
        headers = self._get_auth_header() # 此时还是 Client Token
        
        payload = {
            "code": otp_code,
            "email": email
        }

        print(f"[*] 步骤2: 正在验证 OTP: {otp_code} ...")
        
        try:
            response = self.session.post(url, headers=headers, json=payload, timeout=10)
            
            if response.status_code != 200:
                print(f"[-] 验证失败 (Code: {response.status_code}): {response.text}")
                return None
                
            data = response.json()
            
            # 尝试从不同字段提取 Token
            new_token = data.get("token") or data.get("access_token")
            if not new_token and "data" in data:
                if isinstance(data["data"], dict):
                    new_token = data["data"].get("token")
            
            if new_token:
                self.user_token = new_token
                print(f"[+] 登录成功! User Token: {self.user_token[:30]}...")
                return self.user_token
            else:
                print(f"[-] 未找到 Token。API 响应: {json.dumps(data)}")
                return None

        except Exception as e:
            print(f"[-] 验证过程发生错误: {e}")
            raise

    def get_user_profile(self) -> Dict[str, Any]:
        """
        步骤 3: 获取当前用户资料
        """
        if not self.user_token:
            print("[-] 错误: 未登录，无法获取个人资料。")
            return {}

        url = f"{self.BASE_API_URL}/user/profile"
        headers = self._get_auth_header()
        
        print(f"[*] 步骤3: 获取用户资料...")
        try:
            response = self.session.get(url, headers=headers, timeout=10)
            response.raise_for_status()
            return response.json()
        except Exception as e:
            print(f"[-] 获取资料失败: {e}")
            raise

    def update_user_profile(self, first_name: str, last_name: str, country_code: str = "US") -> Dict[str, Any]:
        """
        步骤 4: 更新用户个人资料 (名字, 国家)
        
        Args:
            first_name (str): 名
            last_name (str): 姓
            country_code (str): 国家代码 (ISO 3166-1 alpha-2, e.g., 'US', 'CN', 'TW')
        """
        if not self.user_token:
            print("[-] 错误: 未登录，无法更新资料。")
            return {}

        url = f"{self.BASE_API_URL}/user/profile/update"
        headers = self._get_auth_header()
        
        payload = {
            "first_name": first_name,
            "last_name": last_name,
            "home_country_code": country_code
        }
        
        print(f"[*] 步骤4: 更新用户资料 -> {first_name} {last_name} ({country_code})...")
        
        try:
            response = self.session.post(url, headers=headers, json=payload, timeout=10)
            response.raise_for_status()
            data = response.json()
            print(f"[+] 资料更新成功! 状态码: {response.status_code}")
            return data
        except requests.exceptions.HTTPError as e:
            print(f"[-] HTTP 错误: {e}")
            if e.response is not None:
                print(f"[-] 服务器返回: {e.response.text}")
            raise
        except Exception as e:
            print(f"[-] 更新失败: {e}")
            raise

if __name__ == "__main__":
    # --- 全流程测试示例 ---
    bot = FlexiroamAuth()
    
    # ⚠️ 请确认这里是你的目标邮箱
    target_email = "pd2ozhb@zenvex.edu.pl" 
    
    print("=" * 30)
    print(f"当前测试邮箱: {target_email}")
    print("=" * 30)

    # 1. 询问是否发送验证码 (防止重复发送被封)
    send_choice = input("是否需要发送验证码? (y/n, 默认发送): ").strip().lower()
    if send_choice != 'n':
        try:
            bot.request_login_otp(target_email)
            print("\n✅ 请求已发送，请检查邮箱（包括垃圾邮件箱）。")
        except Exception:
            print("❌ 请求发送失败，程序退出。")
            exit()
    else:
        print("\n⏩ 跳过发送验证码步骤，直接进入验证环节。")
    
    # 2. 循环输入验证码 (允许重试)
    while True:
        otp_input = input(f"\n请输入 {target_email} 收到的验证码 (输入 q 退出): ").strip()
        
        if otp_input.lower() == 'q':
            print("退出程序。")
            break
            
        if otp_input:
            # 3. 验证登录
            token = bot.verify_login_otp(target_email, otp_input)
            
            if token:
                # --- 登录成功，执行后续逻辑并退出循环 ---
                
                # 4. 获取资料
                profile = bot.get_user_profile()
                if profile:
                    user_data = profile.get('data', {})
                    print(f"当前用户: {user_data.get('first_name')} {user_data.get('last_name')}")
                
                # 5. 更新资料 (可选)
                do_update = input("\n是否测试更新个人资料? (y/n, 默认n): ").strip().lower()
                if do_update == 'y':
                    bot.update_user_profile(
                        first_name="Tessie", 
                        last_name="Adam", 
                        country_code="US"
                    )
                    
                    # 6. 再次获取确认更新
                    new_profile = bot.get_user_profile()
                    print("\n--- 更新后的资料 ---")
                    print(json.dumps(new_profile, indent=2, ensure_ascii=False))
                
                break # 成功后退出 while 循环
            else:
                print("⚠️ 验证失败，请检查验证码是否输入正确，或是否已过期。您可以直接重新输入。")
        else:
            print("验证码不能为空。")
