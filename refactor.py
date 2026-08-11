import re
import os

with open('integrated_dataset_agent.py', 'r', encoding='utf-8') as f:
    content = f.read()

# Setup logging at the beginning (after imports)
logging_setup = '''
import logging
import sys

# ==========================================
# Logger Configuration
# ==========================================
os.makedirs(OUTPUT_RESULTS_DIR, exist_ok=True)
logger = logging.getLogger('DatasetAgent')
logger.setLevel(logging.INFO)
# Avoid adding handlers multiple times if module is reloaded
if not logger.handlers:
    fh = logging.FileHandler(os.path.join(OUTPUT_RESULTS_DIR, 'batch_process.log'), encoding='utf-8')
    fh.setLevel(logging.INFO)
    ch = logging.StreamHandler(sys.stdout)
    ch.setLevel(logging.INFO)
    formatter = logging.Formatter('[%(asctime)s] [%(levelname)s] %(message)s', datefmt='%Y-%m-%d %H:%M:%S')
    fh.setFormatter(formatter)
    ch.setFormatter(formatter)
    logger.addHandler(fh)
    logger.addHandler(ch)
'''

content = re.sub(r'(INTEGRATED_FETCHER_MODULE = [^\n]*\n)', r'\1' + logging_setup + '\n', content, count=1)

def repl_print(m):
    inner = m.group(1)
    if '⚠️' in inner or 'WARNING' in inner or 'error' in inner.lower():
        level = 'warning'
    elif '❌' in inner or '崩溃' in inner or '失败' in inner or '异常' in inner:
        level = 'error'
    else:
        level = 'info'
    return f'logger.{level}({inner})'

content = re.sub(r'print\((.*?)\)', repl_print, content)

def repl_log_msg(m):
    inner = m.group(1)
    if '⚠️' in inner or '未命中' in inner:
        level = 'warning'
    elif '❌' in inner or '崩溃' in inner or '失败' in inner:
        level = 'error'
    else:
        level = 'info'
    return f'logger.{level}({inner})'

content = re.sub(r'log_msg\((.*?)\)', repl_log_msg, content)

# Remove the inner log_msg definition
remove_log_msg_def = r'    def log_msg\(msg: str\):.*?            f\.write\(line \+ "\\n"\)\s*'
content = re.sub(remove_log_msg_def, '', content, flags=re.DOTALL)

with open('integrated_dataset_agent.py', 'w', encoding='utf-8') as f:
    f.write(content)
