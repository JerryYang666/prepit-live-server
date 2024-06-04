# Copyright (c) 2024.
# -*-coding:utf-8 -*-
"""
@file: AgentPromptHandler.py
@author: Jerry(Ruihuang)Yang
@email: rxy216@case.edu
@time: 4/11/24 11:48
"""
import boto3
import redis
from boto3.dynamodb.conditions import Key
import logging
import os

logging.basicConfig(level=logging.INFO)


class AgentPromptHandler:
    DYNAMODB_TABLE_NAME = "prepit_agent_prompt"

    def __init__(self):
        self.dynamodb = boto3.resource('dynamodb', region_name='us-east-2',
                                       aws_access_key_id=os.getenv("AWS_ACCESS_KEY_ID_DYNAMODB"),
                                       aws_secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY_DYNAMODB"))
        self.table = self.dynamodb.Table(self.DYNAMODB_TABLE_NAME)
        self.redis_client = redis.Redis(host=os.getenv("REDIS_ADDRESS"), port=6379, protocol=3, decode_responses=True)

    def put_agent_prompt(self, agent_id: str, prompt: str, step: str) -> bool:
        """
        Put the agent prompt into the database.
        :param prompt: The prompt of the agent.
        :param agent_id: The ID of the agent.
        :param step: The step of the agent.
        :return: True if successful, False otherwise.
        """
        try:
            self.table.put_item(
                Item={
                    'agent_id': agent_id,
                    'step': step,
                    'prompt': prompt
                }
            )
            self.__cache_agent_prompt(agent_id, prompt, step)
            return True
        except Exception as e:
            logging.error(f"Error putting the agent prompt into the database: {e}")
            return False

    def get_agent_prompt(self, agent_id: str, step: str) -> str | None:
        """
        Get the agent prompt from the database.
        :param agent_id: The ID of the agent.
        :param step: The step of the agent.
        :return: The prompt of the agent.
        """
        cached_prompt = self.__get_cached_agent_prompt(agent_id, step)
        if cached_prompt:
            logging.info(f"Cache hit, getting the agent prompt from the cache. {agent_id}")
            return cached_prompt
        # if cache miss, get the prompt from the database, and cache it
        logging.info(f"Cache miss, getting the agent prompt from the database. {agent_id}")
        try:
            response = self.table.query(
                KeyConditionExpression=Key('agent_id').eq(agent_id) & Key('step').eq(str(step))
            )
            if response['Items']:
                prompt = response['Items'][0]['prompt']
                self.__cache_agent_prompt(agent_id, prompt, step)
                return prompt
            else:
                return None
        except Exception as e:
            logging.error(f"Error getting the agent prompt from the database: {e}")
            return None

    def cache_agent_all_steps(self, agent_id: str) -> bool:
        """
        Cache all the agent prompts into redis.
        :param agent_id: The ID of the agent.
        :return: True if successful, False otherwise.
        """
        try:
            response = self.table.query(
                KeyConditionExpression=Key('agent_id').eq(agent_id)
            )
            if response['Items']:
                for item in response['Items']:
                    self.__cache_agent_prompt(agent_id, item['prompt'], item['step'])
                    logging.info(f"Cached agent prompt for agent {agent_id} at step {item['step']}")
                return True
            else:
                return False
        except Exception as e:
            logging.error(f"Error caching all prompts for agent into redis: {e}")
            return False

    def __cache_agent_prompt(self, agent_id: str, prompt: str, step: str) -> bool:
        """
        Cache the agent prompt into redis.
        :param agent_id: The ID of the agent.
        :param prompt: The prompt of the agent.
        :param step: The step of the agent.
        :return: True if successful, False otherwise.
        """
        try:
            self.redis_client.set(f"{agent_id}_{step}", prompt)
            return True
        except Exception as e:
            logging.error(f"Error caching the agent prompt into redis: {e}")
            return False

    def __get_cached_agent_prompt(self, agent_id: str, step: str) -> str | None:
        """
        Get the agent prompt from redis.
        :param agent_id: The ID of the agent.
        """
        try:
            return self.redis_client.get(f"{agent_id}_{step}")
        except Exception as e:
            logging.error(f"Error getting the agent prompt from redis cache: {e}")
            return None
