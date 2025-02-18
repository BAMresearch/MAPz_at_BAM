import os
os.environ["CUDA_DEVICE_ORDER"] = "PCI_BUS_ID"
os.environ["CUDA_VISIBLE_DEVICES"] = "3"  # model will be trained on GPU 3

from transformers import pipeline, AutoModelForCausalLM, AutoTokenizer
import torch
from datasets import Dataset
from transformers.pipelines.pt_utils import KeyDataset
from accelerate import PartialState
import pandas as pd
from tqdm import tqdm
import random


device_string = 'auto'
instruction_head = 'Given a chemical synthesis procedure, summarize the procedure in structured output. Use exclusively these markup tags in the structured output, no other tags: <ADD>, <YIELD>, <DISSOLVE>, <STIR>, <WASH>, <DRY>, <CONCENTRATE>, <PURIFY>, <REMOVE>, <FILTER>, <HEAT>, <EXTRACT>, <COOL>, <SYNTHESIZE>, <WAIT>, <PARTITION>, <DEGASS>, <QUENCH>, <RECOVER>, <APPARATUSACTION>, <PRECIPITATE>, <MIX>, <ADJUSTPH>. Give only the output, no explanation. Here is an example:'
example_procedure = 'Procedure: In a flame-dried 100 mL round bottom flask, a mixture of 2.0 mL of furfurylamine (22 mmol) and 3 mL of triethylamine were stirred in 45 mL of dry dichloromethane under nitrogen at 0 °C. Then, 4.4 g of 1-adamantane carbonylchloride (22 mmol) in 5 mL of dry dichloromethane was added slowly, and the solution was allowed to warm to room temperature. After stirring for 1 h at room temperature, the solution was washed with 40 mL of an aqueous ammonium chloride solution (saturated) and 40 mL of an aqueous potassium carbonate solution (5%), the organic layer was separated, dried over MgSO4, filtered, and evaporated to dryness in vacuo. The crude product was recrystallized from heptane/EtOAc = 1:1 (v/v) to yield the product as off-white needles (3.15 g, 55%)'
example_output = 'Output: <ADD> furfurylamine 2.0 mL 22 mmol triethylamine 3 mL dichloromethane 45 mL <COOL> 0 °C <MIX> 1-adamantane carbonylchloride 22 mmol 4.4 g dry dichloromethane 5 mL <ADD> slowly <HEAT> room temperature <STIR> 1 h <WASH> aqueous ammonium chloride solution (saturated) 40 mL aqueous potassium carbonate solution (5%) 40 mL <REMOVE> organic layer <DRY> MgSO4 <FILTER> <REMOVE> in vacuo <PURIFY> heptane/EtOAc = 1:1 (v/v) <YIELD> off-white needles 3.15 g 55 %'


def create_message(procedure):
    return [{"role": "user", "content": f'{instruction_head}\n{example_procedure}\n{example_output}\nProcedure: {procedure}\n'},]


def prepare_inference_data(start_percent, stop_percent):
    x = [i for i in open('in_cleaned.txt', encoding='utf-8') if i != '']
    x = x[int(start_percent*len(x)):int(stop_percent*len(x))]
    return [create_message(x[i]) for i in range(0, len(x))]


def annotate_data(start_percent, stop_percent, minibatches=1000, resume_index=0):
    dataset = prepare_inference_data(start_percent, stop_percent)

    model_id = "meta-llama/Meta-Llama-3.1-8B-Instruct"

    model = AutoModelForCausalLM.from_pretrained(model_id, device_map=device_string, torch_dtype=torch.bfloat16)
    tokenizer = AutoTokenizer.from_pretrained(model_id, trust_remote_code=True, padding_side='left')
    tokenizer.pad_token = tokenizer.eos_token

    pipe = pipeline("text-generation", model=model, tokenizer=tokenizer)

    offset = len(dataset) / minibatches
    for i in tqdm(range(resume_index, minibatches)):
        dataset_batch = Dataset.from_pandas(pd.DataFrame(data={'text': dataset[int(i*offset):int((i+1)*offset)]}))

        for out in pipe(KeyDataset(dataset_batch, "text"), batch_size=24, max_new_tokens=512, do_sample=False, temperature=None, top_p=None):
            with open(f'out_llama_8B_part_{start_percent}-{stop_percent}_raw.txt', 'a') as f:
                for i in out:
                    f.write(i["generated_text"][-1]["content"].replace(example_output[8:], "").replace("\n", "").replace("\t", "") + '\n')


if __name__ == '__main__':
    annotate_data(0.0, 1.0, resume_index=0)
