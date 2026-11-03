"""
豆包视频生成自动化（改进版）
支持多账号池管理和任务分配
"""
import os
import time
import logging
from pathlib import Path
from typing import List, Dict, Optional
from playwright.sync_api import sync_playwright, Page, BrowserContext

logger = logging.getLogger(__name__)


class DoubaoVideoGenerator:
    """豆包视频生成器"""
    
    def __init__(self, project_root: str):
        """
        初始化生成器
        
        Args:
            project_root: 项目根目录
        """
        self.project_root = Path(project_root)
        self.static_dir = self.project_root / "static"
    
    def connect_to_profile(self, profile_dir: str, headless: bool = False) -> tuple:
        """
        连接到指定的 Chrome Profile（接管已登录的浏览器状态）
        
        Args:
            profile_dir: Chrome Profile 目录路径（相对于项目根目录）
            headless: 是否无头模式
            
        Returns:
            (playwright, context, page) 元组
        """
        profile_path = self.project_root / profile_dir
        profile_path.mkdir(parents=True, exist_ok=True)
        
        p = sync_playwright().start()
        try:
            context = p.chromium.launch_persistent_context(
                str(profile_path),
                channel="chrome",
                headless=headless,
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--disable-dev-shm-usage",
                ],
                viewport={"width": 1280, "height": 800},
            )
            page = context.pages[0] if context.pages else context.new_page()
            page.set_default_timeout(15000)
            
            return p, context, page
        except Exception as e:
            p.stop()
            raise e
    
    def check_login_status(self, page: Page) -> bool:
        """
        检查豆包登录状态
        
        Args:
            page: Playwright Page 对象
            
        Returns:
            是否已登录
        """
        try:
            page.goto("https://www.doubao.com/chat", timeout=30000)
            time.sleep(2)
            
            # 检查是否有输入框（已登录的标志）
            if page.locator("[contenteditable=true]").count() > 0:
                logger.info("账号已登录")
                return True
            
            logger.warning("账号未登录，需要手动登录")
            return False
        except Exception as e:
            logger.error(f"检查登录状态失败: {e}")
            return False
    
    def upload_assets_and_send(self, page: Page, task: Dict) -> bool:
        """
        上传资产并发送提示词
        
        Args:
            page: Playwright Page 对象
            task: 任务信息，包含 prompt, assets, shot_no 等
            
        Returns:
            是否成功
        """
        shot_no = task.get("shot_no", "?")
        assets = task.get("assets", [])
        prompt = task.get("prompt", "")
        
        logger.info(f"开始处理分镜 {shot_no}，资产数: {len(assets)}, 提示词长度: {len(prompt)}")
        
        try:
            # 1. 聚焦输入框
            editor = page.locator("[contenteditable=true]").first
            editor.click()
            time.sleep(0.5)
            
            # 2. 上传资产文件（图片 + 音频）
            if assets:
                # 验证文件存在
                valid_assets = []
                for asset_path in assets:
                    if os.path.exists(asset_path):
                        valid_assets.append(asset_path)
                    else:
                        logger.warning(f"文件不存在: {asset_path}")
                
                if valid_assets:
                    try:
                        # 找到文件上传 input
                        page.set_input_files("input[type=file]", valid_assets)
                        logger.info(f"已上传 {len(valid_assets)} 个资产文件")
                        
                        # 等待缩略图加载
                        time.sleep(2)
                        for _ in range(10):
                            try:
                                # 检查缩略图数量
                                img_count = page.evaluate("""() => {
                                    const imgs = document.querySelectorAll('img');
                                    let count = 0;
                                    imgs.forEach(img => {
                                        const src = img.src || '';
                                        if (src.includes('byteimg') || src.includes('tos-cn')) {
                                            count++;
                                        }
                                    });
                                    return count;
                                }""")
                                if img_count >= len([a for a in valid_assets if a.lower().endswith(('.png', '.jpg', '.jpeg', '.webp'))]):
                                    break
                            except:
                                pass
                            time.sleep(1)
                    except Exception as e:
                        logger.error(f"上传资产失败: {e}")
            
            # 3. 填写提示词
            if prompt:
                try:
                    page.evaluate("""(text) => {
                        const editor = document.querySelector('[contenteditable=true]');
                        if (editor) {
                            editor.focus();
                            document.execCommand('insertText', false, text);
                        }
                    }""", prompt)
                    logger.info(f"已填写提示词")
                except Exception as e:
                    logger.warning(f"填写提示词失败，尝试备用方法: {e}")
                    try:
                        editor.fill(prompt)
                    except:
                        editor.type(prompt, delay=5)
                
                time.sleep(1)
            
            # 4. 发送（按回车）
            editor.press("Enter")
            time.sleep(1)
            
            # 兜底：如果回车没生效，点击发送按钮
            try:
                page.evaluate("""() => {
                    const buttons = document.querySelectorAll('button');
                    for (const btn of buttons) {
                        const text = (btn.textContent || '').trim();
                        const label = btn.getAttribute('aria-label') || '';
                        if (text === '↑' || label === '发送' || text === '发送') {
                            btn.click();
                            break;
                        }
                    }
                }""")
            except:
                pass
            
            logger.info(f"分镜 {shot_no} 已发送")
            return True
            
        except Exception as e:
            logger.error(f"处理分镜 {shot_no} 失败: {e}")
            return False
    
    def generate_batch(
        self,
        profile_dir: str,
        tasks: List[Dict],
        interval: int = 3
    ) -> Dict:
        """
        批量生成视频
        
        Args:
            profile_dir: Chrome Profile 目录
            tasks: 任务列表，每个任务包含 shot_no, prompt, assets
            interval: 每条任务之间的间隔（秒）
            
        Returns:
            生成结果统计
        """
        result = {
            "success": [],
            "failed": [],
            "total": len(tasks)
        }
        
        p, context, page = None, None, None
        
        try:
            # 连接到浏览器
            p, context, page = self.connect_to_profile(profile_dir)
            
            # 检查登录状态
            if not self.check_login_status(page):
                raise Exception("账号未登录，请先在浏览器中登录豆包")
            
            # 逐个处理任务
            for task in tasks:
                shot_no = task.get("shot_no", "?")
                try:
                    success = self.upload_assets_and_send(page, task)
                    if success:
                        result["success"].append(shot_no)
                    else:
                        result["failed"].append(shot_no)
                except Exception as e:
                    logger.error(f"处理分镜 {shot_no} 异常: {e}")
                    result["failed"].append(shot_no)
                
                # 间隔等待
                time.sleep(interval)
            
            logger.info(f"批量生成完成: 成功 {len(result['success'])}, 失败 {len(result['failed'])}")
            
        except Exception as e:
            logger.error(f"批量生成异常: {e}")
            raise
        finally:
            # 清理资源
            if context:
                try:
                    context.close()
                except:
                    pass
            if p:
                try:
                    p.stop()
                except:
                    pass
        
        return result
