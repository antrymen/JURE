import unittest
from jure.ablation.protocol import Controller,Budget,whitelist
class ProtocolTests(unittest.TestCase):
 def test_without_critic_no_hidden_route(self):
  c=Controller('without_critic')
  with self.assertRaises(ValueError):c.handoff('critic','review')
  c.handoff('investigator','investigate');c.handoff('STOP','done')
  self.assertNotIn('critic',str(c.events))
 def test_full_feedback_executed(self):
  c=Controller('full')
  for actor in ['critic','investigator','critic','explorer','critic','STOP']:c.handoff(actor,'reason')
  self.assertEqual(len(c.events),6)
 def test_missing_usage_fail_closed(self):
  b=Budget();b.reserve(10,20)
  with self.assertRaises(RuntimeError):b.settle(None)
  with self.assertRaises(RuntimeError):b.reserve(10,20)
 def test_shared_budget_not_reset(self):
  b=Budget(input_limit=30,output_limit=20);b.reserve(10,10);b.settle({'input_tokens':10,'output_tokens':10})
  with self.assertRaises(RuntimeError):b.reserve(21,10)
  b.reserve(20,10);b.settle({'input_tokens':20,'output_tokens':10})
  with self.assertRaises(RuntimeError):b.reserve(1,1)
 def test_whitelist_nested_leak(self):
  c={'mechanistic_question':'SECRET','clue':{'perturbation':'X','reference_id':'r','pattern':{'genes':['A'],'states':[1],'secret':'SECRET'},'perturbation_shift':{'delta_frequency':.1,'secret':'SECRET'}}}
  self.assertNotIn('SECRET',str(whitelist(c,'M01')))
 def test_single_continuous(self):
  c=Controller('single')
  with self.assertRaises(ValueError):c.handoff('investigator','delegate')
  c.handoff('STOP','done')
if __name__=='__main__':unittest.main()
