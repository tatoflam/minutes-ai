import os
import json
import openai
from logging import getLogger
import time

from prompt import summary_system_content, summary_user_content, \
    summary_chunks_user_content, translation_system_content, \
    translation_user_content, continue_content, \
    chat_detect_lang_content, summary_template, refine_template, \
    map_template, combine_template
from constants import gpt_model, whisper_model, openai_api_key_name
from openai.openai_object import OpenAIObject

from langchain.llms import OpenAI
from langchain.chat_models import ChatOpenAI
from langchain.docstore.document import Document
from langchain.chains.summarize import load_summarize_chain
from langchain.prompts import PromptTemplate
from langchain.callbacks import get_openai_callback

logger = getLogger(__name__)

def set_key():
    # This function is used only when open ai api is directly used (without langchain wrapper)
    openai.api_key = os.environ.get(openai_api_key_name)

def detect_lang(text):
    logger.debug(f"Detecting language by chat completion...")
    detected_lang = openai.ChatCompletion.create(
        model=gpt_model,
        messages=[
            {"role": "system", "content": summary_system_content},
            {"role": "user", 
             "content": chat_detect_lang_content.format(text=text)
             }
            # {"role": "assistant", "content": ""}
        ]
    )
    return detected_lang    

def transcribe(filename, org_lang):
    logger.info(f"Processing file: {filename}")
    audio_file= open(filename, "rb")
    transcribed = openai.Audio.transcribe(model=whisper_model, 
                                            file=audio_file,
                                            temperature=0.1,
                                            language=org_lang)
    
    transcript = transcribed["text"].encode('utf-8').decode('utf-8')
    return transcript

def transcribe_files(script_file, filenames, org_lang):
    transcripts = str()
    logger.debug("Transcribing from the audio file.")
    for filename in filenames:
        transcript = transcribe(filename, org_lang)
        transcripts += transcript + " "
        time.sleep(3)

    with open(script_file, "w") as file:
        file.write(transcripts)
        
    return transcripts
                
def summarize_chunk(transcript, org_lang=None, user_prompt=None):
    summary = openai.ChatCompletion.create(
        model=gpt_model,
        messages=[
            {"role": "system", "content": summary_system_content},
            {"role": "user", 
             "content": summary_user_content.format(
                 org_lang=org_lang, transcript=transcript,
                 user_prompt=user_prompt
                 )
             }
            # {"role": "assistant", "content": ""}
        ]
    )
    return summary

def summarize_chunks(transcript, i, total, summary=None, org_lang=None,
                     user_prompt=None):
    summary = openai.ChatCompletion.create(
        model=gpt_model,
        messages=[
            {"role": "system", "content": summary_system_content},
            {"role": "user", 
             "content": summary_chunks_user_content.format(
                 org_lang=org_lang, transcript=transcript, i=i, total=total,
                 summary=summary, user_prompt=user_prompt
                 )
             }
            # {"role": "assistant", "content": ""}
        ]
    )
    return summary

def get_summarized_content(transcripts, org_lang=None, user_prompt=None):
    num_chunks = len(transcripts)
    contents = str()
    usages = []
    api_tokens = 0
    if num_chunks == 1:
        transcript = transcripts[0]
        summary = summarize_chunk(transcript, org_lang, user_prompt)
        summary_contents, summary_api_tokens, summary_usage = \
            parse_openai_object(summary)
        contents = summary_contents
        api_tokens = summary_api_tokens
        usages.extend(summary_usage)
        
    else:
        summary = str()
        for i in range(num_chunks):
            logger.info(f"--- summarizing chunk: '{i}' ---")
            # logger.info(transcripts[i])
            summary = summarize_chunks(transcripts[i], i, num_chunks, 
                                       summary, org_lang, user_prompt)
            summary_contents, summary_api_tokens, summary_usage = \
                parse_openai_object(summary)
            contents += summary_contents
            api_tokens += summary_api_tokens
            logger.debug(type(summary_usage))
            logger.debug(summary_usage)
            logger.debug(str(summary_usage))

            usages.extend(summary_usage)
    logger.info(f"Summary: API token counted: {api_tokens}")
    return contents, api_tokens, usages

def continue_prompt():
    response = openai.ChatCompletion.create(
        model=gpt_model,
        messages=[
            {"role": "system", "content": summary_system_content},
            {"role": "user", 
             "content": continue_content}
            # {"role": "assistant", "content": ""}
        ]
    )
    return response

def get_summarized_content_by_langchain(transcripts, 
                                        org_lang=None,
                                        chain_type="refine"):
    llm = ChatOpenAI(temperature=0, model_name=gpt_model, request_timeout=120)
    docs = [Document(page_content=t) for t in transcripts]

    summary_prompt = PromptTemplate(template=summary_template, input_variables=["text","org_lang"])
    
    total_tokens = 0
    prompt_tokens = 0
    completion_tokens = 0
    total_cost = 0
    
    if chain_type == "refine":
        refine_prompt = PromptTemplate(
            input_variables=["existing_answer", "text"],
            template=refine_template,
        )
    
        chain = load_summarize_chain(
            llm, chain_type="refine", return_intermediate_steps=True, question_prompt=summary_prompt, refine_prompt=refine_prompt,
            verbose=False)

    elif chain_type == "map_reduce":
        chain = load_summarize_chain(
            llm, chain_type=chain_type, return_intermediate_steps=True, map_prompt=summary_prompt, combine_prompt=summary_prompt,
            verbose=False)
        
    else:
        # Call "stuff" chain for each doc
        # 
        map_prompt = PromptTemplate(template=map_template, input_variables=["text", "org_lang"])
        
        stuff_chain = load_summarize_chain(llm=llm,
                             chain_type="stuff",
                             prompt=map_prompt)
        
        summary_list = []
        for i, doc in enumerate(docs):
            with get_openai_callback() as cb:
                chunk_summary = stuff_chain({"input_documents": [doc], "org_lang": org_lang})["output_text"]
                total_tokens += cb.total_tokens
                prompt_tokens += cb.prompt_tokens
                completion_tokens += cb.completion_tokens
                total_cost += cb.total_cost
                
            summary_list.append(chunk_summary)
            print (f"Summary #{i} - Preview: {chunk_summary[:250]} \n")
        
        summaries = ",".join(summary_list)
        # Convert it back to a document
        summaries = Document(page_content=summaries)

        print (f"Your total summary with combining 'stuff' chain has {llm.get_num_tokens(summaries.page_content)} tokens")

        combine_prompt = PromptTemplate(template=combine_template, input_variables=["text","org_lang"])
        
        chain = load_summarize_chain(
            llm, chain_type="stuff", prompt=combine_prompt, verbose=False)

    with get_openai_callback() as cb:
        contents = chain({"input_documents": docs, "org_lang": org_lang}, return_only_outputs=True)
        token_infos = [json.dumps({
            "Total Tokens": total_tokens + cb.total_tokens,
            "Prompt Tokens": prompt_tokens + cb.prompt_tokens,
            "Completion Tokens": completion_tokens + cb.completion_tokens,
            "Total Cost (USD)": total_cost + cb.total_cost
        })]
    
        logger.info(f"Summarized")
        
        #return contents, api_tokens, usages
        return contents, cb.total_tokens, token_infos


def translate(summary, translate_lang):
    translation = openai.ChatCompletion.create(
        model=gpt_model,
        messages=[
            # Switching system content from the prior one does not work?
            # {role": "system", "content": summary_system_content},
            {"role": "system", "content": translation_system_content},
            {"role": "user", 
             "content": translation_user_content.format(
                 summary=summary, lang=translate_lang)}
            # {"role": "assistant", "content": ""}
        ]
    )
    return translation

def get_translated_content(summary, translate_lang):
    translation = translate(summary, translate_lang)
    content, api_tokens, usages = parse_openai_object(translation)
    return content, api_tokens, usages

def check_openai_content(response):
    isOpenAIContent = False
    if not isinstance(response, str):
        logger.debug("String content was not responded")
        if isinstance(response, OpenAIObject):
            logger.debug("OpenAIObject is responded")
            content = response["choices"][0]["message"]["content"]
            if isinstance(content, str):
                isOpenAIContent = True
    return isOpenAIContent

def parse_openai_object(response):
    contents = str()
    usages = []
    api_tokens_counted = 0
    
    if check_openai_content(response):
        api_tokens_counted = response["usage"]["total_tokens"]
        usages.append(response["usage"])
        for i, choice in enumerate(response["choices"]):
            logger.info(f"--- choice: {i} ---")
            
            finish_reason = choice["finish_reason"]
            contents += choice["message"]["content"]
            
            # Check finish_response
            logger.info(f"finish_reason: '{finish_reason}'")
            if finish_reason == "stop":
                pass
            else:
                while True:
                    logger.info("Continuing prompt...")
                    continue_response = continue_prompt()
                    c, t, u = parse_openai_object(continue_response)
                    logger.info(f"--- continue content ---\n{continue_content}")

                    #contents += c
                    contents = c
                    api_tokens_counted += t
                    usages.append(u)
    
                    continue_finish_reason = continue_response["choices"][0]["finish_reason"]                               
                    logger.info(f"Continue finish reason: '{continue_finish_reason}'")
                    if continue_finish_reason=="stop":
                        
                        break
    else:
        logger.error(f"cannot retrieve OpenAI API Object from {response}")
    return contents, api_tokens_counted, usages
