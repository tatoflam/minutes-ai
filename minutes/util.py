import math
import string
import json
import whisper
import tiktoken
from logging import getLogger
from constants import temp_short_mp3, num_short_text
from langdetect import detect, lang_detect_exception
from openai.openai_object import OpenAIObject

iso639_1_langs = ['aa', 'ab', 'af', 'am', 'ar', 'as', 'ay', 'az', 'ba', 'be', 'bg', 'bh', 'bi', 'bn', 'bo', 'br', 'ca', 'co', 'cs', 'cy', 'da', 'de', 'dz', 'el', 'en', 'eo', 'es', 'et', 'eu', 'fa', 'fi', 'fj', 'fo', 'fr', 'fy', 'ga', 'gd', 'gl', 'gn', 'gu', 'ha', 'hi', 'hr', 'hu', 'hy', 'ia', 'ie', 'ik', 'in', 'is', 'it', 'iw', 'ja', 'ji', 'jw', 'ka', 'kk', 'kl', 'km', 'kn', 'ko', 'ks', 'ku', 'ky', 'la', 'ln', 'lo', 'lt', 'lv', 'mg', 'mi', 'mk', 'ml', 'mn', 'mo', 'mr', 'ms', 'mt', 'my', 'na', 'ne', 'nl', 'no', 'oc', 'om', 'or', 'pa', 'pl', 'ps', 'pt', 'qu', 'rm', 'rn', 'ro', 'ru', 'rw', 'sa', 'sd', 'sg', 'sh', 'si', 'sk', 'sl', 'sm', 'sn', 'so', 'sq', 'sr', 'ss', 'st', 'su', 'sv', 'sw', 'ta', 'te', 'tg', 'th', 'ti', 'tk', 'tl', 'tn', 'to', 'tr', 'ts', 'tt', 'tw', 'uk', 'ur', 'uz', 'vi', 'vo', 'wo', 'xh', 'yi', 'yo', 'za', 'zh', 'zu']

logger = getLogger(__name__)
      
def detect_lang_by_whisper():
    model = whisper.load_model("base")

    # load audio and pad/trim it to fit 30 seconds
    audio = whisper.load_audio(temp_short_mp3)
    audio = whisper.pad_or_trim(audio)

    # make log-Mel spectrogram and move to the same device as the model
    mel = whisper.log_mel_spectrogram(audio).to(model.device)

    # detect the spoken language
    _, probs = model.detect_language(mel)
    detected_lang = max(probs, key=probs.get)
    logger.info(f"Detected language: {detected_lang}")

    # decode the audio
    options = whisper.DecodingOptions(fp16 = False)
    result = whisper.decode(model, mel, options)

    # print the recognized text
    logger.debug(result.text)
    return detected_lang

def get_short_text(script_file):

    # 'iso-8859-1': Latin
    with open(script_file,'r', encoding='utf-8') as f:
        # Get the file size
        text = f.read() 
        middle_start = len(text) // 2 - (num_short_text // 2)
        middle_end = len(text) // 2 + (num_short_text // 2)
        while not ( text[middle_start].isspace() or \
            text[middle_start] in string.punctuation):
            middle_start +=1
            middle_end +=1
            if text[middle_start] == " ":
                middle_start +=1
                middle_end +=1
                break
        middle_chars = text[middle_start:middle_end]
        
        logger.info(f"{num_short_text} characters in the middle of transcript: '{middle_chars}'")
    return middle_chars    
    
def detect_lang_code(text):
    try:
        # Use langdetect to detect the language of the text
        lang_code = detect(text)

        # Check if the detected language code is compliant with ISO-639-1
        if lang_code in [lang.lower() for lang in iso639_1_langs]:
            logger.info(f"detected lang by langdetect:{lang_code}")
            return lang_code
        else:
            logger.warn(f"detected lang:{lang_code} is not in the list. ")
            return lang_code

    except lang_detect_exception.LangDetectException as e:
        raise e(f"Cannot detect lang code for text: {text}")

def detect_lang_by_langdetect(script_file):
    # read the 30 characters in the middle position of a text file:
    short_text = get_short_text(script_file)
    detected_lang = detect_lang_code(short_text)
    logger.debug(f"detected_lang: {detected_lang}")
    return detected_lang

def tokenize(model_name, text):

    encoding = tiktoken.encoding_for_model(model_name)
    tokens = encoding.encode(text)
    tokens_count = len(tokens)

    # logger.info(f"Number of tokens in the transcript: {tokens_count}")
    return tokens, tokens_count

def split_transcript(model_name, tokens, max_token_length):
    
    encoding = tiktoken.encoding_for_model(model_name)

    start_pos = 0
    end_pos = max_token_length
    
    num_chunk = math.ceil(len(tokens) / max_token_length)
    transcripts = []
    
    for _ in range(num_chunk):
        splitted_transcript = encoding.decode(tokens[start_pos:end_pos])
        transcripts.append(splitted_transcript)
        start_pos = end_pos
        end_pos = end_pos + max_token_length
    
    return transcripts

def serialize(obj):
    if isinstance(obj, list):
        obj = obj[0]
    
    if isinstance(obj, OpenAIObject):
        # Serialize the OpenAIObject as a dictionary
        return obj.to_dict()
    if isinstance(obj, str):
        json_string = json.dumps(obj, default=serialize, indent=4)
    else:
        # Use the default serialization function for other objects
        return json.JSONEncoder().default(obj)

    # json_string = json.dumps(obj, default=serialize, indent=4)
    return json_string