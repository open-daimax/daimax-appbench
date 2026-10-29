"""Validated configuration for the current hierarchical scoring algorithm."""
from pydantic import BaseModel, ConfigDict, Field, model_validator
from .policy import ITEMS, OVERALL_WEIGHTS, QUALITY_ANCHORS, DEDUCTION_POINTS

RUNTIME_DEFAULTS = {'open_failed':100,'blank':100,'persistent_loading':60,'script_exception':20,'general_request_failure':10,'critical_resource_failure':25}

class ScoringSettings(BaseModel):
    model_config = ConfigDict(extra='forbid')
    overall_weights: dict[str,float] = Field(default_factory=lambda:dict(OVERALL_WEIGHTS))
    item_weights: dict[str,float] = Field(default_factory=lambda:{k:v['weight'] for k,v in ITEMS.items()})
    quality_anchors: dict[str,float] = Field(default_factory=lambda:dict(QUALITY_ANCHORS))
    deduction_points: dict[str,float] = Field(default_factory=lambda:dict(DEDUCTION_POINTS))
    checkpoint_deductions: dict[str,float] = Field(default_factory=lambda:{'partial':8,'no':20})
    creative_scope_caps: dict[str,str] = Field(default_factory=lambda:{'none':'none','surface_style':'competent','distinctive_expression':'considered','integrated_expression':'exceptional'})
    desktop_usability_caps: dict[str,str] = Field(default_factory=lambda:{'clear':'exceptional','strained':'considered','difficult':'basic','blocked':'weak'})
    device_layout_cap: str | None = 'basic'
    adaptation_failed_device_cap: str | None = 'competent'
    runtime_penalty_weight: float = Field(.20,ge=0,le=1)
    runtime_deductions: dict[str,float] = Field(default_factory=lambda:dict(RUNTIME_DEFAULTS))
    geometry_deductions: dict[str,float] = Field(default_factory=lambda:{'clipped_control':20,'overflow_only':8})

    @model_validator(mode='after')
    def validate_scoring(self):
        specs=[('overall_weights',set(OVERALL_WEIGHTS)),('item_weights',set(ITEMS)),
               ('quality_anchors',set(QUALITY_ANCHORS)),('deduction_points',set(DEDUCTION_POINTS)),
               ('checkpoint_deductions',{'partial','no'}),('runtime_deductions',set(RUNTIME_DEFAULTS)),
               ('geometry_deductions',{'clipped_control','overflow_only'})]
        for key,expected in specs:
            values=getattr(self,key)
            maximum=1 if key.endswith('weights') else 100
            if set(values)!=expected or any(not 0<=v<=maximum for v in values.values()):
                raise ValueError(f'{key}: invalid keys or values')
        if abs(sum(self.overall_weights.values())-1)>1e-6:
            raise ValueError('overall_weights must sum to 1')
        for group in ('visual','information','adaptation'):
            if abs(sum(self.item_weights[k] for k,v in ITEMS.items() if v['group']==group)-1)>1e-6:
                raise ValueError(f'item_weights for {group} must sum to 1')
        if set(self.creative_scope_caps)!={'none','surface_style','distinctive_expression','integrated_expression'} or self.creative_scope_caps['none']!='none' or any(v not in set(QUALITY_ANCHORS)|{'none'} for v in self.creative_scope_caps.values()):
            raise ValueError('creative_scope_caps: invalid scope or anchor')
        if set(self.desktop_usability_caps)!={'clear','strained','difficult','blocked'} or any(v not in QUALITY_ANCHORS for v in self.desktop_usability_caps.values()):
            raise ValueError('desktop_usability_caps: invalid level or anchor')
        for name in ('device_layout_cap','adaptation_failed_device_cap'):
            if getattr(self,name) is not None and getattr(self,name) not in QUALITY_ANCHORS:
                raise ValueError(f'{name}: invalid anchor')
        anchors=[self.quality_anchors[k] for k in QUALITY_ANCHORS]
        if any(a>=b for a,b in zip(anchors,anchors[1:])) or anchors[-1]>=100:
            raise ValueError('quality_anchors must increase strictly and remain below 100')
        return self
