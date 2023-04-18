import os

base_dir = os.path.dirname(__file__)
logging_conf = os.path.join(base_dir, 'config/logging.json')
gpt_model = "gpt-3.5-turbo"
max_token_length = 4097
token_overhead = 1000
whisper_model = "whisper-1"
whisper_pricing_per_min = 0.006 # as of April 2023
gpt_pricing_per_1k_token = 0.002
num_short_text = 100
temp_short_mp3 = "./data/temp_short.mp3"
openai_api_key_name = "OPENAI_API_KEY"