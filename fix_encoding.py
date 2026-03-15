# -*- coding: utf-8 -*-
import os
import codecs

def convert_to_utf8(file_path):
    """将文件转换为UTF-8无BOM编码"""
    try:
        # 以二进制模式读取
        with open(file_path, 'rb') as f:
            content_bytes = f.read()
        
        # 尝试用常见编码解码
        decoded = False
        content = None
        
        # 尝试 UTF-8
        try:
            content = content_bytes.decode('utf-8')
            decoded = True
            print(f"已UTF-8: {file_path}")
        except UnicodeDecodeError:
            pass
        
        # 尝试 GBK
        if not decoded:
            try:
                content = content_bytes.decode('gbk')
                decoded = True
                print(f"转换GBK->UTF-8: {file_path}")
            except UnicodeDecodeError:
                pass
        
        # 如果还没成功，尝试 GB2312（忽略错误）
        if not decoded:
            content = content_bytes.decode('gb2312', errors='ignore')
            print(f"转换GB2312->UTF-8 (忽略错误): {file_path}")
        
        # 写回UTF-8
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(content)
            
    except Exception as e:
        print(f"处理失败 {file_path}: {e}")

def main():
    templates_dir = os.path.join('app', 'templates')
    for root, dirs, files in os.walk(templates_dir):
        for file in files:
            if file.endswith('.html'):
                file_path = os.path.join(root, file)
                convert_to_utf8(file_path)
    print("所有模板文件转换完成。")

if __name__ == '__main__':
    main()