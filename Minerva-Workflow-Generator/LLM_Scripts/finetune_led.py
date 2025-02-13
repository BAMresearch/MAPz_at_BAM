import os
os.environ["CUDA_DEVICE_ORDER"] = "PCI_BUS_ID"
os.environ["CUDA_VISIBLE_DEVICES"] = "3"  # model will be trained on GPU 3

import torch
from datasets import load_dataset, Dataset
from peft import LoraConfig, AutoPeftModelForCausalLM
from transformers import AutoModelForSeq2SeqLM, AutoTokenizer, Seq2SeqTrainer, Seq2SeqTrainingArguments, DataCollatorForSeq2Seq, BitsAndBytesConfig
import pandas as pd
import numpy as np
import random


SEED = 123
random.seed(SEED)
np.random.seed(SEED)

model = None
tokenizer = None

base_model_id = 'allenai/led-base-16384'
finetuned_model_id = "English_To_Actiongraph_LED-Base-16384"


def prepare_train_data():
    x = [i.replace('\r', '').replace('\n', '') for i in open('in_cleaned.txt', encoding='utf-8') if i != '']
    y = [i.replace('\r', '').replace('\n', '') for i in open('out_llama_cleaned.txt', encoding='utf-8') if i != '']

    tmp = list(zip(x, y))
    random.shuffle(tmp)
    x, y = zip(*tmp)

    data_train = Dataset.from_pandas(pd.DataFrame(data={'inputs': [x[i] for i in range(0, int(0.9*len(x)))], 'labels': [y[i] for i in range(0, int(0.9*len(y)))]}))
    data_val = Dataset.from_pandas(pd.DataFrame(data={'inputs': [x[i] for i in range(int(0.9*len(x)), len(x))], 'labels': [y[i] for i in range(int(0.9*len(y)), len(y))]}))
    return data_train, data_val


def get_model_and_tokenizer(model_id):
    tokenizer = AutoTokenizer.from_pretrained(model_id)

    actionTokens = [i.replace('\r', '').replace('\n', '') for i in open('actionDict.txt')]
    tokenizer.add_tokens(actionTokens)

    model = AutoModelForSeq2SeqLM.from_pretrained(model_id)
    model.resize_token_embeddings(len(tokenizer))

    return model, tokenizer


def preprocess_function(raw_data):
    global tokenizer
    model_inputs = tokenizer(raw_data['inputs'], text_target=raw_data['labels'], max_length=1024, truncation=True)
    return model_inputs


def finetune_bigbirdpegasus(base_model_id, finetuned_model_id):
    global model, tokenizer

    data_train, data_val = prepare_train_data()
    model, tokenizer = get_model_and_tokenizer(base_model_id)
    data_train = data_train.map(preprocess_function, batched=True, remove_columns='inputs')
    data_val = data_val.map(preprocess_function, batched=True, remove_columns='inputs')

    training_arguments = Seq2SeqTrainingArguments(
        output_dir=finetuned_model_id,
        per_device_train_batch_size=8,
        learning_rate=5e-5,
        lr_scheduler_type="cosine",
        warmup_ratio=0.05,
        save_strategy="steps",
        eval_strategy="epoch",
        save_steps=10000,
        save_total_limit=3,
        logging_steps=1,
        num_train_epochs=5,
        max_steps=-1,
        push_to_hub=False
    )
    trainer = Seq2SeqTrainer(
        model=model,
        train_dataset=data_train,
        eval_dataset=data_val,
        args=training_arguments,
        tokenizer=tokenizer,
        data_collator = DataCollatorForSeq2Seq(tokenizer=tokenizer, model=model, label_pad_token_id=-100),
    )
    trainer.train()


if __name__ == "__main__":
    finetune_bigbirdpegasus(base_model_id, finetuned_model_id)
