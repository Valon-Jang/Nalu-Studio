import tempfile, unittest, wave
from pathlib import Path
from scripts.luna_quality.adapters.chatterbox_ve_adapter import ChatterboxVEAdapter
from scripts.luna_quality.adapters.speechbrain_adapter import SpeechBrainAdapter
from scripts.luna_quality.contracts import ValidationStatus
from scripts.luna_quality.validators.speaker_identity import CalibrationSample, SpeakerIdentityValidator, calibrate
class FakeVE:
 def embeds_from_wavs(self,wavs,sample_rate,as_spk):
  import numpy as np
  return np.array([float(np.mean(wavs[0])), float(np.std(wavs[0])), 1.0])
def wav(path, amp=0.2, rate=16000):
 import math
 data=bytearray(int(amp*math.sin(i/10)*32767).to_bytes(2,'little',signed=True) for i in [])
 samples=[int(amp*math.sin(i/10)*32767) for i in range(rate//4)]
 with wave.open(str(path),'wb') as f: f.setnchannels(1);f.setsampwidth(2);f.setframerate(rate);f.writeframes(b''.join(x.to_bytes(2,'little',signed=True) for x in samples))
class SpeakerTest(unittest.TestCase):
 def setUp(self): self.d=tempfile.TemporaryDirectory();self.a=Path(self.d.name)/'a.wav';self.b=Path(self.d.name)/'b.wav';wav(self.a);wav(self.b,0.4)
 def tearDown(self): self.d.cleanup()
 def test_same_and_scaled_waveforms_score(self):
  a=ChatterboxVEAdapter(FakeVE(),Path(self.d.name)/'cache'); x,_,_=a.embed(self.a);y,_,_=a.embed(self.a);z,_,_=a.embed(self.b);self.assertAlmostEqual(a.cosine(x,y),1);self.assertGreater(a.cosine(x,z),.9)
 def test_cache_hit_and_invalidation(self):
  a=ChatterboxVEAdapter(FakeVE(),Path(self.d.name)/'cache');a.embed(self.a);self.assertTrue(a.embed(self.a)[2]);wav(self.a,0.3);self.assertFalse(a.embed(self.a)[2])
 def test_uncalibrated_never_hard_passes(self):
  r=SpeakerIdentityValidator(ChatterboxVEAdapter(FakeVE(),Path(self.d.name)/'cache')).validate(self.a,self.b);self.assertEqual(r.status,ValidationStatus.UNKNOWN);self.assertFalse(r.hard_gate)
 def test_calibration_and_missing_data(self):
  self.assertEqual(calibrate([])['status'],'insufficient_data');r=calibrate([CalibrationSample('candidate_b',.9),CalibrationSample('approved_luna',.8),CalibrationSample('drift_rejected',.2)]);self.assertEqual(r['status'],'calibrated_candidate')
 def test_missing_optional_dependency(self): self.assertEqual(SpeechBrainAdapter(package_name='missing_luna_sb').capability().status,ValidationStatus.NOT_RUN)
if __name__=='__main__':unittest.main()
