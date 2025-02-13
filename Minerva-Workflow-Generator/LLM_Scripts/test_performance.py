import timeit

from transformers import pipeline, AutoModelForCausalLM, AutoModelForSeq2SeqLM, AutoTokenizer
import torch
from tqdm import tqdm


model = None
tokenizer = None

if torch.cuda.is_available():
    device = 1  # -1: Run on CPU; 1: Run on GPU 1
else:
    device = -1

torch.set_num_threads(12)


def create_message(procedure):
    instruction_head = 'Given a chemical synthesis procedure, summarize the procedure in structured output. Use exclusively these markup tags in the structured output, no other tags: <ADD>, <YIELD>, <DISSOLVE>, <STIR>, <WASH>, <DRY>, <CONCENTRATE>, <PURIFY>, <REMOVE>, <FILTER>, <HEAT>, <EXTRACT>, <COOL>, <SYNTHESIZE>, <WAIT>, <PARTITION>, <DEGASS>, <QUENCH>, <RECOVER>, <APPARATUSACTION>, <PRECIPITATE>, <MIX>, <ADJUSTPH>. Give only the output, no explanation. Here is an example:'
    example_procedure = 'In a flame-dried 100 mL round bottom flask, a mixture of 2.0 mL of furfurylamine (22 mmol) and 3 mL of triethylamine were stirred in 45 mL of dry dichloromethane under nitrogen at 0 °C. Then, 4.4 g of 1-adamantane carbonylchloride (22 mmol) in 5 mL of dry dichloromethane was added slowly, and the solution was allowed to warm to room temperature. After stirring for 1 h at room temperature, the solution was washed with 40 mL of an aqueous ammonium chloride solution (saturated) and 40 mL of an aqueous potassium carbonate solution (5%), the organic layer was separated, dried over MgSO4, filtered, and evaporated to dryness in vacuo. The crude product was recrystallized from heptane/EtOAc = 1:1 (v/v) to yield the product as off-white needles (3.15 g, 55%)'
    example_output = 'Output: <ADD> furfurylamine 2.0 mL 22 mmol triethylamine 3 mL dichloromethane 45 mL <COOL> 0 °C <MIX> 1-adamantane carbonylchloride 22 mmol 4.4 g dry dichloromethane 5 mL <ADD> mixture slowly <HEAT> room temperature <STIR> 1 h <WASH> aqueous ammonium chloride solution (saturated) 40 mL aqueous potassium carbonate solution (5%) 40 mL <EXTRACT> organic layer <DRY> MgSO4 <FILTER> <REMOVE> in vacuo <PURIFY> heptane/EtOAc = 1:1 (v/v) <YIELD> off-white needles 3.15 g 55 %'
    return f'{instruction_head}\n{example_procedure}\n{example_output}\nProcedure: {procedure}\n'


def get_examples(n=3):
    x = [i for i in open('in_cleaned.txt', encoding='utf-8')]
    x.sort(key = len)
    return [x[int((i+1)/(n+1)*len(x))] for i in range(0, n)]


def run_benchmark(model_id, number_of_repeats=3):
    global model, tokenizer, prompts, device

    if 'llama' in model_id:
        model = AutoModelForCausalLM.from_pretrained(model_id, torch_dtype=torch.bfloat16)
        tokenizer = AutoTokenizer.from_pretrained(model_id, trust_remote_code=True, padding_side='left')
        tokenizer.pad_token = tokenizer.eos_token
        prompts = [create_message(prompt) for prompt in prompts]
    elif 'BigBirdPegasus' in model_id or 'LED-Base-16384' in model_id:
        model = AutoModelForSeq2SeqLM.from_pretrained(model_id, torch_dtype=torch.bfloat16)
        tokenizer = AutoTokenizer.from_pretrained(model_id, trust_remote_code=True)
    else:
        raise NotImplementedError

    if 'llama' in model_id:
        print(timeit.timeit("run_inference_llama(model, tokenizer, prompts)", globals=globals(), number=number_of_repeats))
    elif 'BigBirdPegasus' in model_id:
        print(timeit.timeit("run_inference_pegasus(model, tokenizer, prompts)", globals=globals(), number=number_of_repeats))
    elif 'LED-Base-16384' in model_id:
        print(timeit.timeit("run_inference_led(model, tokenizer, prompts)", globals=globals(), number=number_of_repeats))


def run_inference_llama(model, tokenizer, prompts):
    for prompt in prompts:
        pipe = pipeline("text-generation", model=model, tokenizer=tokenizer, device=device)
        pipe(prompt, max_new_tokens=512, do_sample=False, temperature=None, top_p=None)


def run_inference_pegasus(model, tokenizer, prompts):
    for prompt in prompts:
        pipe = pipeline("text2text-generation", model=model, tokenizer=tokenizer, device=device)
        pipe(prompt, max_new_tokens=512, do_sample=False, temperature=None, top_p=None)


def run_inference_led(model, tokenizer, prompts):
    for prompt in prompts:
        pipe = pipeline("text2text-generation", model=model, tokenizer=tokenizer, device=device)
        pipe(prompt, max_new_tokens=1024, do_sample=False, temperature=None, top_p=None)


if __name__ == '__main__':
    prompts = get_examples()
    print(f"Length of examples (before tokenization): {', '.join([str(len(prompt)) for prompt in prompts])}\n\n")

    for model_id in ('meta-llama/Meta-Llama-3.1-8B-Instruct', './BigBirdPegasus_Chemtagger', './LED-Base-16384_Chemtagger'):
        print(f'Benchmark for model {model_id.split("/")[1]}:')
        print('-'*30)
        run_benchmark(model_id)
        print('\n\n')
