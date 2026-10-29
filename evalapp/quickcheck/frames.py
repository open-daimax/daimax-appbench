"""Dependency-free 64-bit perceptual hashing with semantic/local-change guards."""
import math
from statistics import median

from PIL import Image, ImageChops, ImageStat

_COS=tuple(tuple(math.cos((2*x+1)*u*math.pi/64) for x in range(32)) for u in range(8))


def perceptual_hash(path):
    """DCT pHash. Hashes are compared only within the same viewport."""
    with Image.open(path) as source:
        pixels=list(source.convert('L').resize((32,32),getattr(Image,'Resampling',Image).LANCZOS).tobytes())
    rows=[[sum(pixels[y*32+x]*_COS[u][x] for x in range(32)) for u in range(8)] for y in range(32)]
    coefficients=[sum(rows[y][u]*_COS[v][y] for y in range(32)) for v in range(8) for u in range(8)]
    threshold=median(coefficients[1:])
    # Exclude DC; pin its bit to zero so brightness alone cannot dominate similarity.
    bits=sum((coefficient>threshold)<<i for i,coefficient in enumerate(coefficients) if i)
    return f'{bits:016x}'


def hash_distance(a,b):
    return (int(a,16)^int(b,16)).bit_count()


def pixel_difference(a,b):
    with Image.open(a) as first,Image.open(b) as second:
        if first.size!=second.size:
            return 1.,1.
        diff=ImageChops.difference(first.convert('RGB'),second.convert('RGB'))
        whole=sum(ImageStat.Stat(diff).mean)/(3*255)
        maximum=0.
        for y in range(0,diff.height,64):
            for x in range(0,diff.width,64):
                tile=diff.crop((x,y,min(x+64,diff.width),min(y+64,diff.height)))
                maximum=max(maximum,sum(ImageStat.Stat(tile).mean)/(3*255))
    return whole,maximum


def semantically_equal(a,b):
    keys=('text','loading_visible','pending_images','broken_images','fonts_ready','document_state','horizontal_overflow')
    return all(a['dom'].get(key)==b['dom'].get(key) for key in keys) and a.get('pending_critical')==b.get('pending_critical')


def near_duplicate(a,b,output,settings):
    if not semantically_equal(a,b):
        return False
    if hash_distance(a['phash'],b['phash'])>settings.phash_distance:
        return False
    whole,local=pixel_difference(output/a['screenshot'],output/b['screenshot'])
    return whole<=settings.dedup_pixel_threshold and local<=settings.dedup_local_threshold


def select_representatives(samples,output,settings):
    """Keep the final frame and at most one distinct, late, ready-state peer.

    Never replace the final evidence with an early loading frame. Deduplication
    changes model inputs only; all temporal observations remain in the report.
    """
    if not samples:
        return [],0
    last=samples[-1]
    selected=[last]
    duplicates=0
    # Consider only the recent readiness-confirmation window, not startup frames.
    for sample in reversed(samples[-settings.stable_samples:-1]):
        dom=sample['dom']
        if dom.get('loading_visible') or not dom.get('fonts_ready',True) or dom.get('pending_images',0) or sample.get('pending_critical',0) or not dom.get('meaningful',True):
            continue
        if near_duplicate(sample,last,output,settings):
            duplicates+=1
        elif len(selected)<2:
            selected.insert(0,sample)
    return selected,duplicates
