import os
import configparser
from dotenv import load_dotenv

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
load_dotenv(os.path.join(PROJECT_ROOT, '.env'))

config = configparser.ConfigParser()
config.read(os.path.join(PROJECT_ROOT, 'config', 'config.ini'))


def get_llm_api_key():
    api_key = os.getenv('LLM_API_KEY')
    if api_key:
        return api_key
    if 'llm' in config and 'api_key' in config['llm']:
        return config['llm']['api_key']
    raise RuntimeError(
        'LLM API key not found in .env or config/config.ini ([llm] section)')


def get_llm_base_url():
    url = os.getenv('LLM_BASE_URL')
    if url:
        return url
    if 'llm' in config and 'base_url' in config['llm']:
        return config['llm']['base_url']
    return 'https://genai.hkbu.edu.hk/api/v0/rest'


def get_llm_model():
    model = os.getenv('LLM_MODEL')
    if model:
        return model
    if 'llm' in config and 'model' in config['llm']:
        return config['llm']['model']
    return 'gpt-4.1'


def get_llm_api_ver():
    ver = os.getenv('LLM_API_VER')
    if ver:
        return ver
    if 'llm' in config and 'api_ver' in config['llm']:
        return config['llm']['api_ver']
    return '2024-12-01-preview'


API_KEY = get_llm_api_key()
BASE_URL = get_llm_base_url()
MODEL = get_llm_model()
API_VER = get_llm_api_ver()

try:
    from ChatGPT_HKBU import ChatGPT
    chatgpt = ChatGPT(api_key=API_KEY, base_url=BASE_URL,
                      model=MODEL, api_ver=API_VER)
except ImportError:
    chatgpt = None


def get_llm_response(prompt: str) -> str:
    if chatgpt is None:
        return '[LLM Error] ChatGPT_HKBU package not installed.'
    try:
        response = chatgpt.get_completion(prompt)
        return response.strip()
    except Exception as e:
        return f"[LLM Error] {e}"
