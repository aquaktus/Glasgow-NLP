import random
import re
import copy
import torch
from time import perf_counter
from itertools import compress as mask
import tqdm
from src.FasterMCTS import FasterMCTS
from torch.utils.data import Dataset, DataLoader
from pytorch_lightning import Trainer, Callback, seed_everything

class AlphaZero_Trainer():
    def __init__(self, model, env):
        self.model = model
        self.env = env
        
    def execute_episodes(self, problem_type='simple_addition', episodes=100, simulations=800, force_states=None, force_targets=None, seed=None):
        current_states, target_strings = self.env.random_states(episodes, problem_type, seed=seed)
        if type(force_states)!=type(None):
            current_states, target_strings = force_states, force_targets
        len_unique = len(target_strings)
        print(f'For {episodes} episodes found {len_unique} unique.')
        
        examples = [[]]*len(target_strings)
        final_examples = []
        mcts = FasterMCTS(self.model, self.env)
        
        t1 = perf_counter()  
        while examples != []:
            # theres still a probllem here when using 90 episodes
            for i in tqdm.tqdm(range(simulations), desc=f'Sims for {len(target_strings)} episodes'): mcts.search(current_states, target_strings)
            pi_s = mcts.getActionProb(current_states)
            
            current_strings = self.env.to_hash(current_states)
            for i in range(current_states.shape[0]):
                examples[i].append({'current_state':current_states[i].clone(), 
                                    'current_string': current_strings[i],
                                     'target_string': target_strings[i],
                                     'top_pi_actions': self.env.to_hash(pi_s[i].argsort(descending=True)[:10].unsqueeze(1)),
                                     'top_pi_action_ids': pi_s[i].argsort(descending=True)[:10],
                                     'pi':pi_s[i], 
                                     'reward':None})              # rewards can not be determined yet 
            
            sampled_actions = pi_s.multinomial(1)    # sample action from improved policy
            next_states, rewards, is_terminal_mask = self.env.step(current_states, target_strings, sampled_actions)
            
            for i in range(current_states.shape[0]):
                if is_terminal_mask[i] == True:
                    episode_reward = rewards[i]
                    finished_examples = self.assignRewards(examples[i], episode_reward)
                    final_examples += finished_examples
            
            examples = list(mask(examples,~is_terminal_mask))
                    
            current_states = next_states[~is_terminal_mask]
            target_strings = list(mask(target_strings,~is_terminal_mask))
            print(f'{is_terminal_mask.sum()} terminated, {current_states.shape[0]} left.')
            
        t2 = perf_counter()
        print(f'Performed {len_unique} episodes in {t2-t1:.2f}s.')
        return final_examples
    
    def assignRewards(self, examples, reward):
        for ex in examples:
            ex['reward'] = reward
        return examples
    
    def decomposePositiveEpisodes(self, current_states, target_strings):
        examples = []
        for i in range(current_states.shape[0]):
            examples += self.decomposePositiveEpisode(current_states[i][current_states[i] != self.env.PAD_id], target_strings[i])
        return examples
    
    def decomposePositiveEpisode(self, current_state, target_string):
        examples = []
        sp_mask = self.env.singleAutoGeneratedMask(current_state)
        for i in range(current_state.shape[0]):
            if sp_mask[i] == True:
                continue
            one_hot_pi = torch.zeros(self.env.getActionSize(), dtype=torch.float)
            one_hot_pi[current_state[i]] = 1
            new_example = {'current_state':current_state[:i], 
                           'target_string':target_string,
                           'pi': one_hot_pi,
                           'id': 'custom',
                           'reward':1
                          }
            examples.append(new_example)
        return examples