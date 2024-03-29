import torch
import torch.nn as nn
from torch.distributions import Categorical

from src.models.model_common import get_encoding, _to_tensor, Encoder, Decoder, Value, Policy


class TSPModel(nn.Module):
    def __init__(self, **model_params):
        super(TSPModel, self).__init__()

        self.model_params = model_params

        self.policy_net = Policy(**model_params)
        self.value_net = Value(**model_params)
        self.encoder = Encoder(2, **model_params)
        self.decoder = Decoder(model_params['embedding_dim'], **model_params)

        self.encoding = None

    def _get_obs(self, observations, device):
        observations = _to_tensor(observations, device)
        
        xy = observations['xy']
        # (N, 2), (N, 1)

        cur_node = observations['pos']
        # (1, )

        available = observations['available']
        # (1, )
        
        batch_size, pomo_size, _ = available.size()

        xy = xy.reshape(batch_size, -1, 2)
        
        if cur_node is not None:
            cur_node = cur_node.reshape(batch_size, pomo_size, 1)

        available = available.reshape(batch_size, pomo_size, -1)

        return xy, cur_node, available

    def forward(self, obs):
        xy, cur_node, available = self._get_obs(obs, self.device)
        # xy: (B, N, 2)
        # cur_node: (B, pomo, )
        # available: (B, pomo, N)
        
        batch_size, pomo_size, N = available.size()
        
        mask = torch.zeros_like(available).type(torch.float32)
        mask[available == False] = float('-inf')

        if self.encoding is None:
            self.encoding = self.encoder(xy)
            self.decoder.set_kv(self.encoding)
        
        if cur_node is None:
            selected = torch.arange(pomo_size)[None, :].expand(batch_size, pomo_size).to(self.device)
            probs = torch.zeros(size=(batch_size, pomo_size, N)).to(self.device)
            probs = probs.scatter(2, selected[:, :, None], 1)
            # assign prob 1 to the next nodes for each pomo

            cur_node_encoding = get_encoding(self.encoding, selected[:, :, None])
            self.decoder.set_q_first_node(cur_node_encoding)

            mh_attn_out = self.decoder(cur_node_encoding, load=None, mask=mask)

            val = self.value_net(mh_attn_out)
            val = val.reshape(batch_size, pomo_size, 1)

        else:
            cur_node_encoding = get_encoding(self.encoding, cur_node.long())
            mh_attn_out = self.decoder(cur_node_encoding, load=None, mask=mask)
            
            probs = self.policy_net(mh_attn_out, self.decoder.single_head_key, mask)
            probs = probs.reshape(batch_size, pomo_size, N)        
            
            val = self.value_net(mh_attn_out)
            val = val.reshape(batch_size, pomo_size, 1)
            
        return probs, val

