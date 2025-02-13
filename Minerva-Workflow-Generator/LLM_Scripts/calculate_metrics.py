import os
os.environ["CUDA_DEVICE_ORDER"] = "PCI_BUS_ID"
os.environ["CUDA_VISIBLE_DEVICES"] = "3"  # model will be evaluated on GPU 3

import torch
from datasets import load_dataset, Dataset
from transformers import BigBirdPegasusForConditionalGeneration, LEDForConditionalGeneration, AutoTokenizer
import evaluate

import pandas as pd
import numpy as np
import random

from tqdm import tqdm

SEED = 123
random.seed(SEED)
np.random.seed(SEED)

model = None
tokenizer = None
MAX_LENGTH = 512

rouge = evaluate.load('rouge')
bleu = evaluate.load('bleu')


def prepare_data(labels='out_llama_cleaned.txt'):
    global SEED
    random.seed(SEED)
    x = [i.replace('\r', '').replace('\n', '') for i in open('in_cleaned.txt', encoding='utf-8') if i != '']
    y = [i.replace('\r', '').replace('\n', '') for i in open(labels, encoding='utf-8') if i != '']

    tmp = list(zip(x, y))
    random.shuffle(tmp)
    x, y = zip(*tmp)

    data_train = Dataset.from_pandas(pd.DataFrame(data={'inputs': [x[i] for i in range(0, int(0.9*len(x)))], 'labels': [y[i] for i in range(0, int(0.9*len(y)))]}))
    data_val = Dataset.from_pandas(pd.DataFrame(data={'inputs': [x[i] for i in range(int(0.9*len(x)), len(x))], 'labels': [y[i] for i in range(int(0.9*len(y)), len(y))]}))
    return data_train, data_val


def get_model_and_tokenizer(model_path):
    global tokenizer, model, MAX_LENGTH
    tokenizer = AutoTokenizer.from_pretrained(model_path)
    if '_LED-Base' in model_path:
        model = LEDForConditionalGeneration.from_pretrained(model_path).to("cuda")
        MAX_LENGTH = 1024
    else:
        model = BigBirdPegasusForConditionalGeneration.from_pretrained(model_path).to("cuda")
        MAX_LENGTH = 512
    return model, tokenizer


def generate_answer(batch):
    global tokenizer, model, MAX_LENGTH
    t = tokenizer(batch["inputs"], padding=True, max_length=MAX_LENGTH, return_tensors="pt", truncation=True).to("cuda")
    pred_ids = model.generate(input_ids=t.data['input_ids'], attention_mask=t.data['attention_mask'], max_length=MAX_LENGTH, do_sample=False)

    batch["predicted"] = tokenizer.batch_decode(pred_ids, skip_special_tokens=True)
    return batch


def evaluate_model(gt_data, preds=None):
    global rouge, bleu

    inputs = gt_data.remove_columns('labels')
    refs = gt_data['labels']

    if preds is None:
        preds = inputs.map(generate_answer, batched=True, batch_size=15)["predicted"]

    rouge_results = rouge.compute(predictions=preds, references=refs)
    bleu_results = bleu.compute(predictions=preds, references=refs)

    return rouge_results, bleu_results


if __name__ == '__main__':
    rouge = evaluate.load('rouge')
    bleu = evaluate.load('bleu')

    _, data_val = prepare_data(labels='out_llama_cleaned.txt')

   with open('evaluation_results.csv', 'w') as f:
       f.write('model;rouge1;rouge2;rougeL;rougeLsum;bleu;precisions;brevity_penalty;length_ratio;translation_length;reference_length\n')

   for model_path in tqdm(('English_To_Actiongraph_BigBirdPegasus_Chemtagger', 'English_To_Actiongraph_LED-Base-16384_Chemtagger', 'English_To_Actiongraph_BigBirdPegasus_Llama', 'English_To_Actiongraph_LED-Base-16384_Llama')):
       model, tokenizer = get_model_and_tokenizer(model_path)
       rouge_results, bleu_results = evaluate_model(data_val, preds=None)
       with open('evaluation_results.csv', 'a') as f:
           f.write(model_path + ';' + ';'.join(str(i) for i in rouge_results.values()) + ';' + ';'.join(str(i) for i in bleu_results.values()) + '\n')

    for model_path in tqdm(('out_chemtagger_raw.txt', 'out_chemtagger_cleaned.txt', 'out_llama_raw.txt')):
        _, preds = prepare_data(labels=model_path)

        rouge_results, bleu_results = evaluate_model(data_val, preds=preds['labels'])
        with open('evaluation_results.csv', 'a') as f:
            f.write(model_path + ';' + ';'.join(str(i) for i in rouge_results.values()) + ';' + ';'.join(str(i) for i in bleu_results.values()) + '\n')
