# Copyright (c) 2024.
# -*-coding:utf-8 -*-
"""
@file: ChatStream.py
@author: Jerry(Ruihuang)Yang
@email: rxy216@case.edu
@time: 2/29/24 15:14
"""
from typing import List
import json
from pydantic import BaseModel
from TtsStream import TtsStream
from PromptManager import PromptManager
import uuid
# from common.AgentPromptHandler import AgentPromptHandler


class ChatStreamModel(BaseModel):
    dynamic_auth_code: str
    messages: dict[int, dict[str, str]]
    current_step: int
    agent_id: str
    thread_id: str | None = None
    provider: str = "openai"


class ChatSingleCallResponse(BaseModel):
    status: str  # "success" or "fail"
    error_message: str | None = None
    messages: List[str]
    thread_id: str


class ChatStreamResponse(BaseModel):
    status: str  # "success" or "fail"
    error_message: str | None = None
    messages: List[str]
    thread_id: str


class ChatStream:
    """
    ChatStream: AI chat with OpenAI/Anthropic, streams the output via server-sent events.
    Using this class need to pass in the full messages history, and the provider (openai or anthropic).
    """

    def __init__(self, sio_server, openai_client, anthropic_client):
        self.openai_client = openai_client
        self.anthropic_client = anthropic_client
        self.sio_server = sio_server

        self.tts_session_id = str(uuid.uuid4())
        self.tts = TtsStream(self.tts_session_id)

    async def stream_chat(self, chat_stream_model: ChatStreamModel, requested_provider, current_step, agent_id, sid):
        messages = self.__messages_processor(chat_stream_model.messages, agent_id, current_step)
        async for message in self.__chat_generator(messages, requested_provider):
            await self.sio_server.emit("downlink_chat_message",
                                       {"response": message, "tts_session_id": self.tts_session_id}, room=sid)

    async def __chat_generator(self, messages: List[dict[str, str]], requested_provider):
        """
        Chat generator.
        :param messages:
        :return:
        """
        if requested_provider == "openai":
            print("Using OpenAI")
            stream = self.__openai_chat_generator(messages)
        elif requested_provider == "anthropic":
            print("Using Anthropic")
            stream = self.__anthropic_chat_generator(messages)
        else:
            stream = self.__openai_chat_generator(messages)
        response_text = ""
        chunk_id = -1  # chunk_id starts from 0, -1 means no chunk has been created
        sentence_ender = [".", "?", "!"]
        chunk_buffer = ""
        async for text_chunk in stream:
            new_text = text_chunk
            response_text += new_text
            if len(chunk_buffer.split()) > (16 + (chunk_id * 13)):  # dynamically adjust the chunk size
                if sentence_ender[0] in new_text and not chunk_buffer[-1].isnumeric():  # if the chunk contains a sentence ender . and the last character is not a number
                    chunk_buffer, chunk_id = self.__process_chunking(sentence_ender[0], new_text, chunk_buffer,
                                                                     chunk_id)
                elif sentence_ender[1] in new_text:  # if the chunk contains a sentence ender ?
                    chunk_buffer, chunk_id = self.__process_chunking(sentence_ender[1], new_text, chunk_buffer,
                                                                     chunk_id)
                elif sentence_ender[2] in new_text:  # if the chunk contains a sentence ender !
                    chunk_buffer, chunk_id = self.__process_chunking(sentence_ender[2], new_text, chunk_buffer,
                                                                     chunk_id)
                else:  # if the chunk does not contain a sentence ender
                    chunk_buffer += new_text
            else:  # if the chunk is less than 21 words
                chunk_buffer += new_text
            yield json.dumps(
                {"response": response_text, "tts_session_id": self.tts_session_id,
                 "tts_max_chunk_id": chunk_id})
        # Process any remaining text in the chunk_buffer after the stream has finished
        if chunk_buffer:
            chunk_id += 1
            self.tts.stream_tts(chunk_buffer, str(chunk_id))
            yield json.dumps(
                {"response": response_text, "tts_session_id": self.tts_session_id, "tts_max_chunk_id": chunk_id})

    async def __openai_chat_generator(self, messages: List[dict[str, str]]):
        """
        OpenAI chat generator.
        :param messages:
        :return:
        """
        with self.openai_client.chat.completions.create(
                model="gpt-4o",
                messages=messages,
                stream=True,
                max_tokens=256,
                temperature=0.92,
        ) as stream:
            for chunk in stream:
                if chunk.choices[0].delta.content is not None:
                    new_text = chunk.choices[0].delta.content
                    yield new_text

    async def __anthropic_chat_generator(self, messages: List[dict[str, str]]):
        """
        Anthropic chat generator.
        :param messages:
        :return:
        """
        system_message_content = ""
        if messages[0]["role"] == "system":
            system_message = messages.pop(0)
            system_message_content = system_message["content"]
        with self.anthropic_client.messages.stream(
                system=system_message_content,
                max_tokens=2048,
                messages=messages,
                model="claude-3-sonnet-20240229",
        ) as stream:
            for text in stream.text_stream:
                if text is not None:
                    yield text

    def __process_chunking(self, sentence_ender: str, new_text: str, chunk_buffer: str, chunk_id: int):
        """
        Process the chunking.
        :param sentence_ender:
        :param new_text:
        :param chunk_buffer:
        :param chunk_id:
        :return:
        """
        chunk_id += 1
        new_text_split = new_text.split(sentence_ender)
        chunk_buffer += new_text_split[0] + sentence_ender
        self.tts.stream_tts(chunk_buffer, str(chunk_id))
        chunk_buffer = sentence_ender.join(new_text_split[1:])
        return chunk_buffer, chunk_id

    def __messages_processor(self, messages: dict[int, dict[str, str]], agent_id: str, current_step: int):
        """
        Process the message.
        :param messages: {0: {"role": "user", "content": "Hello, how are you?"}, 1: {"role": "assistant", "content": "I am fine, thank you."}}
        :return:
        """
        # messages_list = [{"role": "system",
        #                  "content": "You are a teaching assistant for the Computational Economics Course. Make sure you sound like someone talking, not writing. Use contractions, and try to be conversational. You should not say very long paragraphs. As someone who is talking, you should be giving short, quick messages. No long paragraphs, No long paragraphs, please."}]
        messages_list = [{"role": "system",
                          "content": """You are an interviewer at McKinsey. You are conducting a case interview with a candidate. This is a Quick ask, quick answer scenario. You should be asking questions and giving short, quick responses. You should not say very long paragraphs. As an interviewer, you should be giving short, quick messages. No long paragraphs, please.
                          Prompt:Our client, Distero, is a large grocery distributor based out of the US. As a result of the COVID-19 pandemic, Distero identified that its customers, US grocery stores, have had significantly increased grocery deliveries to end consumers. Distero is bringing in our team to investigate whether they can, and should, offer direct to consumer (DTC) e-commerce grocery delivery. How would you advise our client?
                                Clarifying Information:(Provide this only if corresponding questions are asked, If candidate asks a question that is not listed here, you should not provide an answer, and should say that question is not relevant to the case.)
                                1. What is the grocery industry value chain?
                                The grocery value chain is largely a “three tier” system whereby food producers sell to distributors who subsequently sell to retail locations primarily restaurants and grocery stores.
                                2. Does our client have any experience with e-commerce?
                                Our client has an existing e-commerce platform that it uses for its current customers (grocers) to purchase goods for delivery.
                                3. What is the client’s objective?
                                Our client is seeking incremental margin in any way shape or form.
                                4. What is our client’s current footprint?
                                Our client has significant penetration throughout the US, but not internationally."""}]
        # current_step = self.agent_prompt_handler.get_agent_prompt(self.agent_id, self.current_step)
        # current_step_info = {}
        # if current_step:
        #     current_step_info = json.loads(current_step)
        messages_list = [{"role": "system",
                          "content": f"{PromptManager.BASE_ROLE}"}]  # Please follow this instruction: {current_step_info['instruction']} Here's some information for you, you should not give the info to candidate directly: {current_step_info['information']}"}]
        print(messages_list)
        for key in sorted(messages.keys()):
            messages_list.append(messages[key])
        return messages_list
