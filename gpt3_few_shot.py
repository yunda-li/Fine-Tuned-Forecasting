# -*- coding: utf-8 -*-
"""GPT3_Few_Shot

Automatically generated by Colab.

Original file is located at
    https://colab.research.google.com/drive/18FfMO4yBSep9zDZpeXIyxDFLrStxQsZE
"""

!pip install transformers datasets openai

import openai
api_key = #USE PERSONAL API KEY HERE
openai.api_key = api_key

import os
import time
import numpy as np
import pandas as pd
os.chdir('/content/drive/Shareddrives/CS542_Competition/Fine_Tuning')

!ls

"""Load and Filter Autocast Training Data"""

from datasets import load_dataset

train_dataset = load_dataset("csv", data_files='autocast_train_questions_combined_with_tf_negated.csv')

#Double check number of entries
train_dataset = train_dataset['train']
train_dataset

#Remove test set questions from training set.

from pandas import *
data = read_csv("autocast_test_set_w_answers.csv")

repeated_questions = data['question'].tolist()

train_dataset = train_dataset.filter(lambda example: not example['question'] in repeated_questions)
train_dataset

#Filter out answers that are None

filtered_dataset = train_dataset.filter((lambda example: not example["answer"] == None)) #and not example["qtype"] == 'num'))

filtered_dataset

#Remove the URLs from the backgrounds and add

import re

def remove_urls(entry):
    '''
        URLs by themselves don't contain any useful information for GPT-3 to interpret. Uses regular expressions to remove any strings with
        typical URL pieces like http:, www, or com, due to some broken up URLs.
        Ex.
            "A launch for military or testing purposes would count, i.e.,
            www.nytimes.com/2012/12/24/world/asia/north-korean-rocket-had-military-purpose-seoul-says.html.
            The success of the launch, and the actual distance traveled, are irrelevant."

            ->

            "A launch for military or testing purposes would count, success of the launch, and the actual distance traveled, are irrelevant."
    '''

    text = entry['background']
    try:

        cleaned_text = re.sub(r'\S+\s*\.\s*\S+', '', text)
        text = re.sub(r'http\S+', '', cleaned_text)
        cleaned_text = re.sub(r'com\S+', '', text)
        text = re.sub(r'www\S+', '', cleaned_text)
        cleaned_text = re.sub(r'\s{2,}', ' ', text)

        entry['background'] = cleaned_text

    except:
        pass

    return entry

cleaned_dataset = filtered_dataset.map(remove_urls)

cleaned_dataset.to_csv('cleaned_train_set.csv')

"""Preprocess Training Data"""

#Split data into t/f, mcq, and num to take random samples for the example tasks in the prompt.

tf_dataset = cleaned_dataset.filter((lambda example: example["qtype"] == 't/f'))
mc_dataset = cleaned_dataset.filter((lambda example: example["qtype"] == 'mc'))
num_dataset = cleaned_dataset.filter((lambda example: example['qtype'] == 'num'))

tf_dataset

mc_dataset

num_dataset

#Remove columns

tf_dataset = tf_dataset.remove_columns(['publish_time', 'close_time', 'source_links', 'prediction_count', 'forecaster_count', 'crowd', 'question_negated', 'id', 'status', 'Unnamed: 0'])
mc_dataset = mc_dataset.remove_columns(['publish_time', 'close_time', 'source_links', 'prediction_count', 'forecaster_count', 'crowd', 'question_negated', 'id', 'status', 'Unnamed: 0'])
num_dataset = num_dataset.remove_columns(['publish_time', 'close_time', 'source_links', 'prediction_count', 'forecaster_count', 'crowd', 'question_negated', 'id', 'status', 'Unnamed: 0'])

mc_dataset[2]

#Split choices

def split_string(entry):
    '''
        All choices in training set are one string. Function splits string into list of strings to allow indexing of each choice.

        Ex.
            "['Majority', 'Plurality', 'Not a Plurality']" -> ['Majority', 'Plurality', 'Not a Plurality']

    '''

    try:
        choices_text = entry['choices'].rstrip("']")

        choices_split = choices_text.replace("', '", '@').split('@')
        choices_split[0] = choices_split[0][2:]
        entry['choices'] = choices_split

    except:
        pass

    return entry

#Map split choices onto neccesary datasets

tf_dataset = tf_dataset.map(split_string)
mc_dataset_split = mc_dataset.map(split_string)

print(mc_dataset_split[4]['choices'])
print(type(mc_dataset_split[4]['choices']))

#Process choices and answers for mc questions

def process_choices(entry):
    '''
        For mc questions, choices are given as differing format from the answers. Function adds corresponding letters to choices, and corresponding choice to answer, so that
        answer always exactly matches one of the choices.

        Ex.
            {'choices' : ['Majority', 'Plurality', 'Not a Plurality'], 'answer': 'A'}

            ->

            {'choices' : ['A: Majority', 'B: Plurality', 'C: Not a plurality'], 'answer': 'A: Majority'}

    '''

    #Process Choices
    if entry['qtype'] == 'mc':
        choices = entry['choices']
        #print(type(choices_text))
        processed_choices = []
        for i, item in enumerate(choices):
            letter = chr(65 + i)  # 65 is the ASCII value for 'A'
            processed_choices.append(f"{letter}: {item}")

        entry['choices'] = processed_choices

    #Process Answer
    try:
        answer = entry['answer']
        final_answer = ''
        for item in processed_choices:
            if item.startswith(answer):
                final_answer = item

        entry['answer'] = final_answer

    except:
        pass

    return entry

#Map function to mc dataset
mc_dataset_split = mc_dataset_split.map(process_choices)

print(mc_dataset_split[1]['choices'])
print(mc_dataset_split[1]['answer'])

for i in range(5):
    print((mc_dataset_split[i]['choices']))
    print((mc_dataset_split[i]['answer']))

for i in range(5):
    print((num_dataset[i]['choices']))
    print((num_dataset[i]['answer']))

#Retrieve 2 example prompts for each question

import random

tf_length = tf_dataset.num_rows
mc_length = mc_dataset.num_rows
num_length = num_dataset.num_rows


def generate_random_subset(dataset):
    '''
        From input dataset, return 2 randomly selected entries from that dataset. To prevent any erroneous associations from repeated answers, after the first
        random selection is made, the 2nd loops until it selects an entry with a different answer.
    '''

    length = dataset.num_rows - 1

    x1 = random.randint(0, length)
    x2 = random.randint(0, length)

    first = dataset.select([x1])
    second = dataset.select([x2])

    #Ensure different answers from the two examples
    if first['qtype'][0] == 'mc':
        while len(first[0]['answer']) > 0 and len(second[0]['answer']) > 0 and first[0]['answer'][0] == second[0]['answer'][0]:
            x2 = random.randint(0, length)
            second = dataset.select([x2])

    elif first['qtype'][0] == 't/f':
        while first['answer'] == second['answer']:
            x2 = random.randint(0, length)
            second = dataset.select([x2])

    return dataset.select([x1, x2])



tf_subset = generate_random_subset(tf_dataset)
mc_subset = generate_random_subset(mc_dataset_split)
num_subset = generate_random_subset(num_dataset)


print(mc_subset[0]['answer'])
print(mc_subset[1]['answer'])

print(num_dataset[20]['answer'])

"""Few-Shot Learning"""

#Core API function

def generate_answer(examples, prompt_entry, max_length=1024):
    '''
        Generates prompt and feeds into GPT-3 API. Randomly generated examples are used as example tasks. Last prompt leaves answer open ended for GPT-3 to answer.

        Ex.
            Question: Will more than 10% of flights departing from Hong Kong Intl. Airport be cancelled on the 16th of August 2019?
            Background: The Hong Kong protesters ...
            Choices: ['yes', 'no']
            Answer: no
            Question: Will there be a new episode of mass killing in Ethiopia before 1 January 2017?
            Background: For more information on what ...
            Choices: ['yes', 'no']
            Answer: yes


            ########

            Question: Will the city of Venice lift its ban on 'Jean A Deux Mamans; or 'Piccolo Uovo' before 1 September 2016?
            Background: There is no indication that Venice ...
            Choices: ['yes', 'no']
            GPT-3 Answer:no
    '''

    #Generate example task
    example_prompt = ""
    for entry in examples:
        background = entry['background']
        if background == None:
            background = ''

        example_prompt += f"Question: {entry['question']}\n Background: {background}\n Choices: {entry['choices'][:]}\n Answer: {entry['answer']}\n "

    #Generate open ended prompt
    prompt = f"{example_prompt}\n\n########\n\n Question: {prompt_entry['question']}\n Background: {prompt_entry['background']}\n Choices: {prompt_entry['choices'][:]}\n GPT-3 Answer:"

    #Generate GPT-3 response
    response = openai.Completion.create(
        engine="text-ada-001",
        prompt=prompt,
        max_tokens=max_length,
        n=1,
        stop=None,
        temperature=0.3, #low temperature is more predictable outputs, high temperature has more creative outputs
    )
    try:
        answer = response.choices[0].text.strip()  #prompt + response.choices[0].text.strip() to see prompt + generation

    except:
        answer = 'N/A'

    return answer

examples = generate_random_subset(tf_dataset)

# Example t/f question
test_dict = {
    'question' : "Will the city of Venice lift its ban on 'Jean A Deux Mamans; or 'Piccolo Uovo' before 1 September 2016?",
    'background' : "There is no indication that Venice has lifted its ban. Venice's mayor banned two books from preschool and elementary schools and libraries, both of which deal with gender issues and same-sex couples; the decision came as the country engages in a heated debate over same-sex marriage (NY Times, International Business Times).",
    'choices' : "['yes', 'no']"
}

answer = generate_answer(examples, test_dict)
print(answer)

#Example mc question and generated answer

test_dict = {
    'question' : "How many seats will the Justice and Development Party (AKP) win in Turkey's snap elections?",
    'background' : "The Justice and Development Party (AKP) failed to win a single-party majority in June's general election for the first time since negotiations aimed at forming a coalition government collapsed, snap elections have been scheduled for 1 more information see: .",
    'choices' : "['A: A majority', 'B: A plurality', 'C: Not a plurality']"
}
examples = generate_random_subset(mc_dataset_split)

answer = generate_answer(examples, test_dict)
print(answer)

#Example num question and answer

test_dict = {
    'question' : "How much global solar photovoltaic electricity-generating capacity, in gigawatts, will be in operation by 2020?",
    'background' : "Worldwide energy demand amounts to around 13 terawatts of amount of energy from renewable sources is a paltry of the world's power GW of that power from solar is currently the leader in solar or photovoltaic (PV) capacity, producing around 40% of the world's solar terms of growth, China and Japan are the global leaders, together 51% of growth in PV installations in of PV installations over the past five years has been phenomenal, with a growth rate of between 29 and 42% every of future growth are equally impressive, ranging from around 400 to nearly 700 GW of PV capacity in have historically underestimated estimate actual growth, prices of PV energy continues to fall (see related question here) and projection methodologies may in some cases fail to capture factors such as transformative technologies that may further drive PV much global solar photovoltaic electricity-generating capacity, in gigawatts, will be in operation by 2020? The definitive source for question resolution will be the annual 'Trends' report from the International Energy Agency's Photovoltaic Power Systems the report covers trends up to the year previous, resolution will be dependent on the report to be issued in late this report should cease publication or substantially change its methodology, question resolves as ambiguous.",
    'choices' : "{'max': 2000, 'min': 200, 'deriv_ratio': 5}"
}
examples = generate_random_subset(num_dataset)

answer = generate_answer(examples, test_dict)
print(answer)

"""
Small Scale Testing on Training Set"""

def make_preds(dataset, batch_size):
    '''
        Makes predictions on dataset by running generate_answer() function on each data entry. Appends GPT-3 generated answer to list.
        A delay of 1 second per entry is added to avoid API input limit of 60 prompts/ min.
    '''

    generated_preds = []
    for i, entry in enumerate(dataset.select(range(batch_size))):
        examples = generate_random_subset(dataset)

        try:
            answer = generate_answer(examples, entry)
            generated_preds.append(answer)

        except:
            answer = f'ERROR: entry #{i}'
            generated_preds.append(answer)

        #Delay to prevent API error
        time.sleep(1)

        #Progress tracker
        if i%50 == 0:
            print(i)

    return generated_preds

#Test small batch of tf questions

print(make_preds(tf_dataset, 5))

#Test small batch of mc questions

print(make_preds(mc_dataset_split, 5))

#Test small batch of num questions

print(make_preds(num_dataset, 5))

"""Few Shot on Training Set to check accuracy"""

#Run on whole train set of tf questions

import warnings
from transformers import logging

# Filter out the warning related to pad_token_id
warnings.filterwarnings("ignore", message="Setting `pad_token_id` to `eos_token_id`:50256 for open-end generation.")


tf_answer_list = []
k = tf_length

tf_answer_list = make_preds(tf_dataset, k)

print(len(tf_answer_list))  #temperature 0.3

#Save generated answers to .txt file

with open('tf_train_answers.txt', 'w') as f:
    for line in tf_answer_list:
        f.write(f"{line}, ")

#Run on whole train set of mc questions


mc_answer_list = []
j = mc_dataset_split.num_rows

mc_answer_list = make_preds(mc_dataset_split, j)

print(len(mc_answer_list))  #temperature 0.3

#Save mc results to .txt file

with open('mc_train_answers.txt', 'w') as f:
    for line in mc_answer_list:
        f.write(f"{line}, ")

#Generate on train set of num questions

num_answer_list = []
n = num_dataset.num_rows

num_answer_list = make_preds(num_dataset, n)

#Save num generations to .txt file
with open('num_train_answers.txt', 'w') as f:
    for line in num_answer_list:
        f.write(f"{line}, ")

print(num_answer_list)

"""Postprocess Few Shotted Results"""

!ls

def read_files(path):
    '''
        Read generated results from .txt files if needed.
    '''

    my_file = open(path, "r")
    data = my_file.read()

    temp_list = data.split(',')
    print(len(temp_list))
    #print(temp_list[:5])
    my_file.close()

    return temp_list

#Process t/f results

def process_tf_results(str_list):
    '''
        remove any spaces and upper case letters from GPT-3 generated answers
    '''

    return [entry.strip().lower() for entry in str_list]

tf_FS_answers = []
tf_answer_1 = tf_answer_list

#tf_answer_1 = read_files('tf_answer_list.txt')
tf_answer_1 = process_tf_results(tf_answer_1)
print(tf_answer_1[:5])


tf_FS_answers.extend(tf_answer_1)

print(len(tf_FS_answers))

#Process mc generated preds

def process_mc_results(result, dataset):
    '''
        Generated mc results sometimes are missing the letter associated to the choice. If the result has the letter, then returns the letter to better match
        for accuracy measurements. Otherwise, searches through choices to look for matching choice with corresponding letter.

        Ex:
            ['A: Yoweri Museveni', 'B: Amama Mbabazi', 'C: Kizza Besigye', 'D: None of the above']
            GPT-3 Answer:Yoweri Museveni

            ->

            GPT-3 Answer: A
    '''
    processed_results = []


    for i, item in enumerate(result):
        #Check for ':', which implies a leading letter
        if item.find(':') != -1:
            letter = item.split(':')[0]
            processed_results.append(letter)

        else:
            #If no ':', find matching choice
            choices = dataset[i]['choices']
            for choice in choices:
                choice_letter = choice.split(':')[0]
                choice_contents = choice.split(':')[1].strip()

                if item.strip().find(choice_contents) != -1:
                    processed_results.append(choice_letter)
                    break
                else:
                    processed_results.append(item)
                    break

    return processed_results

processed_mc_answers = process_mc_results(mc_answer_list, mc_dataset_split)

print(processed_mc_answers[:200])

with open('mc_gpt3_processed_t0.txt', 'w') as f:
    for line in mc_answer_list:
        f.write(f"{line}, ")

import ast

def process_num_results(result, dataset):
    '''
        Dataset numerical answers are given in ratio between 0 and 1, to reflect the answer within a given range. Generated numerical answers are not neccesarily between 0 and 1,
        so this function divides outputs by the given max value if the generated answer is >1. If the generation is erroneous, then returns a random generated number between 0
        and 1.
    '''

    processed_num = []

    for i, item in enumerate(result):
        try:
            ans = float(item)

        except:
            ans = round(random.random(),4)

        if ans > 1:
            data = ast.literal_eval(dataset[i]['choices'])
            max = data['max']

            try:
                ans = ans / max
                if ans > 1:
                    ans = round(random.random(),4)
            except:
                pass


        processed_num.append(ans)


    return processed_num



processed_num_answers = process_num_results(num_answer_list, num_dataset)
print(max(processed_num_answers))

#Calculate accuracy of predicted tf answers

from sklearn.metrics import accuracy_score

test_fs = tf_dataset['answer']
accuracy_score(test_fs, tf_FS_answers)

#Calculate accuracy of predicted mc answers

from sklearn.metrics import accuracy_score

test_mc = mc_dataset['answer']
accuracy_score(test_mc, processed_mc_answers)

"""Load and Process Test Set


"""

#Load test set

test_dataset = load_dataset("csv", data_files='autocast_test_set_w_answers.csv')

test_dataset = test_dataset['train']

test_dataset = test_dataset.map(remove_urls)

test_dataset = test_dataset.map(split_string)

test_dataset = test_dataset.map(process_choices)

test_dataset = test_dataset.remove_columns(['publish_time', 'close_time', 'id', 'Unnamed: 0'])

test_dataset

"""Generate Test Predictions"""

preds = []
r = test_dataset.num_rows

def main():
    for i, entry in enumerate(test_dataset.select(range(r))):
        '''
            Combination of process_tf_results(), process_mc_results(), and process_num_results(), applied to predictions made on test set.
        '''

        if entry['qtype'] == 't/f':
            examples = generate_random_subset(tf_dataset)

        if entry['qtype'] == 'mc':
            examples = generate_random_subset(mc_dataset_split)

        if entry['qtype'] == 'num':
            examples = generate_random_subset(num_dataset)

        try:
            #t/f processing
            if entry['qtype'] == 't/f':
                answer = generate_answer(examples, entry).strip().lower()
                preds.append(answer)

            #mc processing

            if entry['qtype'] == 'mc':
                answer = generate_answer(examples, entry)

                if answer.find(':') != -1:
                    letter = answer.split(':')[0]
                    preds.append(letter)
                else:
                    choices = entry[i]['choices']
                    for choice in choices:
                        choice_letter = choice.split(':')[0]
                        choice_contents = choice.split(':')[1].strip()

                        if answer.strip().find(choice_contents) != -1:
                            preds.append(choice_letter)
                            break
                        else:
                            preds.append(answer)
                            break


            #num processing
            if entry['qtype'] == 'num':
                answer = generate_answer(examples, entry)
                try:
                    ans = float(answer)

                except:
                    ans = round(random.random(),4)

                if ans > 1:
                    data = ast.literal_eval(entry[i]['choices'])
                    max = data['max']

                try:
                    ans = ans / max
                    if ans > 1:
                        ans = round(random.random(),4)
                except:
                    pass


                preds.append(ans)


        except:
            answer = f'ERROR: #{i}'
            preds.append(answer)



        time.sleep(1)

        if i%50 == 0:
            print(i)



main()

print(preds)

import pickle

if not os.path.exists('submission'):
    os.makedirs('submission')

with open(os.path.join('submission', 'predictions.pkl'), 'wb') as f:
    pickle.dump(preds, f, protocol=2)

!cd submission && zip ../submission.zip ./* && cd ..
print("here")

