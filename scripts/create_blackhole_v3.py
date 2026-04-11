import unreal

EAL = unreal.EditorAssetLibrary
MEL = unreal.MaterialEditingLibrary
ATH = unreal.AssetToolsHelpers.get_asset_tools()

material_path = "/Game/M_BlackHole"

# Delete existing asset (safe replacement)
if EAL.does_asset_exist(material_path):
    if not EAL.delete_asset(material_path):
        result = {"error": "Failed to delete existing material"}
        raise Exception("Cannot delete existing asset")
    unreal.SystemLibrary.collect_garbage()

# Create new material
material = ATH.create_asset("M_BlackHole", "/Game/", unreal.Material, unreal.MaterialFactoryNew())
if not material:
    result = {"error": "Failed to create material"}
    raise Exception("Cannot create material")

# Material properties
material.set_editor_property("blend_mode", unreal.BlendMode.BLEND_TRANSLUCENT)
material.set_editor_property("shading_model", unreal.MaterialShadingModel.MSM_UNLIT)
material.set_editor_property("two_sided", True)

# Helper functions
def add_expr(expr_class, pos_x=0, pos_y=0, **kwargs):
    expr = MEL.create_material_expression(material, expr_class, pos_x, pos_y)
    for k, v in kwargs.items():
        try:
            expr.set_editor_property(k, v)
        except:
            pass
    return expr

def conn(from_expr, from_out, to_expr, to_input):
    MEL.connect_material_expressions(from_expr, from_out, to_expr, to_input)

# ============================================================
# SECTION 1: UV & Radial Distance
# ============================================================
tex_coord = add_expr(unreal.MaterialExpressionTextureCoordinate, -1800, 0)
center = add_expr(unreal.MaterialExpressionConstant2Vector, -1800, 200, R=0.5, G=0.5)

sub_uv_center = add_expr(unreal.MaterialExpressionSubtract, -1600, 0)
conn(tex_coord, "", sub_uv_center, "A")
conn(center, "", sub_uv_center, "B")

mask_r = add_expr(unreal.MaterialExpressionComponentMask, -1400, -100, R=True, G=False, B=False, A=False)
mask_g = add_expr(unreal.MaterialExpressionComponentMask, -1400, 100, R=False, G=True, B=False, A=False)
conn(sub_uv_center, "", mask_r, "")
conn(sub_uv_center, "", mask_g, "")

square_x = add_expr(unreal.MaterialExpressionMultiply, -1200, -100)
square_y = add_expr(unreal.MaterialExpressionMultiply, -1200, 100)
conn(mask_r, "", square_x, "A")
conn(mask_r, "", square_x, "B")
conn(mask_g, "", square_y, "A")
conn(mask_g, "", square_y, "B")

add_sq = add_expr(unreal.MaterialExpressionAdd, -1000, 0)
conn(square_x, "", add_sq, "A")
conn(square_y, "", add_sq, "B")

sqrt_dist = add_expr(unreal.MaterialExpressionSquareRoot, -800, 0)
conn(add_sq, "", sqrt_dist, "")

# ============================================================
# SECTION 2: Normalize direction for distortion
# ============================================================
normalize_dir = add_expr(unreal.MaterialExpressionNormalize, -800, 300)
conn(sub_uv_center, "", normalize_dir, "")

# ============================================================
# SECTION 3: Gravitational Lensing (Scene Color distortion)
# ============================================================
distortion_strength = add_expr(unreal.MaterialExpressionScalarParameter, -600, 400,
                                parameter_name="DistortionStrength", default_value=0.12)

mul_distort = add_expr(unreal.MaterialExpressionMultiply, -400, 350)
conn(normalize_dir, "", mul_distort, "A")
conn(distortion_strength, "", mul_distort, "B")

sub_distort = add_expr(unreal.MaterialExpressionSubtract, -200, 300)
conn(tex_coord, "", sub_distort, "A")
conn(mul_distort, "", sub_distort, "B")

scene_color = add_expr(unreal.MaterialExpressionSceneColor, 0, 300)
conn(sub_distort, "", scene_color, "Coordinates")

# ============================================================
# SECTION 4: Event Horizon (center black opaque disk)
# ============================================================
eh_radius = add_expr(unreal.MaterialExpressionScalarParameter, -600, 700,
                      parameter_name="EventHorizonRadius", default_value=0.12)

sub_eh = add_expr(unreal.MaterialExpressionSubtract, -400, 650)
conn(sqrt_dist, "", sub_eh, "A")
conn(eh_radius, "", sub_eh, "B")

sat_eh = add_expr(unreal.MaterialExpressionSaturate, -200, 650)
conn(sub_eh, "", sat_eh, "")

oneminus_eh = add_expr(unreal.MaterialExpressionOneMinus, 0, 650)
conn(sat_eh, "", oneminus_eh, "")

# ============================================================
# SECTION 5: Accretion Disk (glowing ring)
# ============================================================
accretion_inner = add_expr(unreal.MaterialExpressionScalarParameter, -600, 900,
                            parameter_name="AccretionInnerRadius", default_value=0.13)
accretion_outer = add_expr(unreal.MaterialExpressionScalarParameter, -600, 1050,
                            parameter_name="AccretionOuterRadius", default_value=0.55)
accretion_intensity = add_expr(unreal.MaterialExpressionScalarParameter, -600, 1200,
                                parameter_name="AccretionIntensity", default_value=3.0)
accretion_color = add_expr(unreal.MaterialExpressionVectorParameter, -400, 1200,
                            parameter_name="AccretionColor",
                            default_value=unreal.LinearColor(r=1.0, g=0.35, b=0.05, a=1.0))

# (dist - inner) / (outer - inner)
sub_acc_inner = add_expr(unreal.MaterialExpressionSubtract, -400, 900)
conn(sqrt_dist, "", sub_acc_inner, "A")
conn(accretion_inner, "", sub_acc_inner, "B")

sub_acc_outer = add_expr(unreal.MaterialExpressionSubtract, -400, 1050)
conn(accretion_outer, "", sub_acc_outer, "A")
conn(accretion_inner, "", sub_acc_outer, "B")

div_acc = add_expr(unreal.MaterialExpressionDivide, -200, 950)
conn(sub_acc_inner, "", div_acc, "A")
conn(sub_acc_outer, "", div_acc, "B")

sat_acc = add_expr(unreal.MaterialExpressionSaturate, 0, 950)
conn(div_acc, "", sat_acc, "")

oneminus_acc = add_expr(unreal.MaterialExpressionOneMinus, 200, 950)
conn(sat_acc, "", oneminus_acc, "")

power_acc = add_expr(unreal.MaterialExpressionPower, 400, 950)
conn(oneminus_acc, "", power_acc, "Base")
conn(accretion_intensity, "", power_acc, "Exponent")

mul_acc_color = add_expr(unreal.MaterialExpressionMultiply, 600, 1050)
conn(power_acc, "", mul_acc_color, "A")
conn(accretion_color, "", mul_acc_color, "B")

# ============================================================
# SECTION 6: Pulse Animation
# ============================================================
time_expr = add_expr(unreal.MaterialExpressionTime, -600, 1400)
rot_speed = add_expr(unreal.MaterialExpressionScalarParameter, -400, 1400,
                      parameter_name="RotationSpeed", default_value=0.3)

mul_time = add_expr(unreal.MaterialExpressionMultiply, -200, 1400)
conn(time_expr, "", mul_time, "A")
conn(rot_speed, "", mul_time, "B")

sin_pulse = add_expr(unreal.MaterialExpressionSine, 0, 1400)
conn(mul_time, "", sin_pulse, "")

pulse_amp = add_expr(unreal.MaterialExpressionConstant, 0, 1550, R=0.15)
mul_pulse = add_expr(unreal.MaterialExpressionMultiply, 200, 1450)
conn(sin_pulse, "", mul_pulse, "A")
conn(pulse_amp, "", mul_pulse, "B")

const_one = add_expr(unreal.MaterialExpressionConstant, 200, 1300, R=1.0)
add_pulse = add_expr(unreal.MaterialExpressionAdd, 400, 1350)
conn(const_one, "", add_pulse, "A")
conn(mul_pulse, "", add_pulse, "B")

# Modulate accretion with pulse
mul_acc_pulse = add_expr(unreal.MaterialExpressionMultiply, 800, 1100)
conn(mul_acc_color, "", mul_acc_pulse, "A")
conn(add_pulse, "", mul_acc_pulse, "B")

# Multiply by intensity
mul_acc_final = add_expr(unreal.MaterialExpressionMultiply, 1000, 1100)
conn(mul_acc_pulse, "", mul_acc_final, "A")
conn(accretion_intensity, "", mul_acc_final, "B")

# ============================================================
# SECTION 7: Photon Sphere (thin purple/blue ring)
# ============================================================
photon_offset = add_expr(unreal.MaterialExpressionScalarParameter, -600, 1750,
                          parameter_name="PhotonSphereOffset", default_value=0.02)
photon_width = add_expr(unreal.MaterialExpressionScalarParameter, -600, 1900,
                         parameter_name="PhotonSphereWidth", default_value=0.06)
photon_color = add_expr(unreal.MaterialExpressionVectorParameter, -400, 1900,
                         parameter_name="PhotonSphereColor",
                         default_value=unreal.LinearColor(r=0.3, g=0.1, b=0.9, a=1.0))
photon_intensity = add_expr(unreal.MaterialExpressionScalarParameter, -400, 2050,
                             parameter_name="PhotonSphereIntensity", default_value=2.5)

add_photon_start = add_expr(unreal.MaterialExpressionAdd, -400, 1750)
conn(eh_radius, "", add_photon_start, "A")
conn(photon_offset, "", add_photon_start, "B")

sub_photon = add_expr(unreal.MaterialExpressionSubtract, -200, 1750)
conn(sqrt_dist, "", sub_photon, "A")
conn(add_photon_start, "", sub_photon, "B")

div_photon = add_expr(unreal.MaterialExpressionDivide, 0, 1750)
conn(sub_photon, "", div_photon, "A")
conn(photon_width, "", div_photon, "B")

sat_photon = add_expr(unreal.MaterialExpressionSaturate, 200, 1750)
conn(div_photon, "", sat_photon, "")

oneminus_photon = add_expr(unreal.MaterialExpressionOneMinus, 400, 1750)
conn(sat_photon, "", oneminus_photon, "")

power_photon_exp = add_expr(unreal.MaterialExpressionConstant, 400, 1900, R=6.0)
power_photon = add_expr(unreal.MaterialExpressionPower, 600, 1750)
conn(oneminus_photon, "", power_photon, "Base")
conn(power_photon_exp, "", power_photon, "Exponent")

mul_photon_color = add_expr(unreal.MaterialExpressionMultiply, 800, 1850)
conn(power_photon, "", mul_photon_color, "A")
conn(photon_color, "", mul_photon_color, "B")

mul_photon_final = add_expr(unreal.MaterialExpressionMultiply, 1000, 1850)
conn(mul_photon_color, "", mul_photon_final, "A")
conn(photon_intensity, "", mul_photon_final, "B")

# ============================================================
# SECTION 8: Lensing Zone Mask (for edge opacity falloff)
# ============================================================
lensing_radius = add_expr(unreal.MaterialExpressionScalarParameter, -600, 2200,
                           parameter_name="LensingRadius", default_value=0.7)

div_lens = add_expr(unreal.MaterialExpressionDivide, -400, 2200)
conn(sqrt_dist, "", div_lens, "A")
conn(lensing_radius, "", div_lens, "B")

sat_lens = add_expr(unreal.MaterialExpressionSaturate, -200, 2200)
conn(div_lens, "", sat_lens, "")

oneminus_lens = add_expr(unreal.MaterialExpressionOneMinus, 0, 2200)
conn(sat_lens, "", oneminus_lens, "")

# ============================================================
# SECTION 9: Final Composition
# ============================================================

# --- Emissive Color ---
# Total glow = accretion + photon
add_glow = add_expr(unreal.MaterialExpressionAdd, 1200, 1400)
conn(mul_acc_final, "", add_glow, "A")
conn(mul_photon_final, "", add_glow, "B")

# Glow mask for lerp alpha (using the raw mask, not color*mask)
add_glow_mask = add_expr(unreal.MaterialExpressionAdd, 1200, 1000)
conn(power_acc, "", add_glow_mask, "A")
conn(power_photon, "", add_glow_mask, "B")

sat_glow_mask = add_expr(unreal.MaterialExpressionSaturate, 1400, 1000)
conn(add_glow_mask, "", sat_glow_mask, "")

# Lerp: A=SceneColor(distorted), B=GlowColor, Alpha=GlowMask
# Where glow is present → show glow color
# Where glow is absent → show distorted background
lerp_emissive = add_expr(unreal.MaterialExpressionLinearInterpolate, 1600, 800)
conn(scene_color, "", lerp_emissive, "A")
conn(add_glow, "", lerp_emissive, "B")
conn(sat_glow_mask, "", lerp_emissive, "Alpha")

MEL.connect_material_property(lerp_emissive, "", unreal.MaterialProperty.MP_EMISSIVE_COLOR)

# --- Opacity ---
# event_horizon_mask + accretion_mask + photon_mask + lensing_zone_mask
add_opacity_1 = add_expr(unreal.MaterialExpressionAdd, 600, 650)
conn(oneminus_eh, "", add_opacity_1, "A")
conn(power_acc, "", add_opacity_1, "B")

add_opacity_2 = add_expr(unreal.MaterialExpressionAdd, 800, 650)
conn(add_opacity_1, "", add_opacity_2, "A")
conn(power_photon, "", add_opacity_2, "B")

add_opacity_3 = add_expr(unreal.MaterialExpressionAdd, 1000, 650)
conn(add_opacity_2, "", add_opacity_3, "A")
conn(oneminus_lens, "", add_opacity_3, "B")

sat_opacity = add_expr(unreal.MaterialExpressionSaturate, 1200, 650)
conn(add_opacity_3, "", sat_opacity, "")

MEL.connect_material_property(sat_opacity, "", unreal.MaterialProperty.MP_OPACITY)

# Recompile
MEL.recompile_material(material)

result = {
    "status": "ok",
    "path": material_path,
    "material": material.get_name(),
    "blend_mode": "Translucent",
    "shading_model": "Unlit",
    "two_sided": True,
    "parameters": [
        "EventHorizonRadius (0.12) - 事件视界半径",
        "AccretionInnerRadius (0.13) - 吸积盘内径",
        "AccretionOuterRadius (0.55) - 吸积盘外径",
        "AccretionIntensity (3.0) - 吸积盘发光强度",
        "AccretionColor (1.0, 0.35, 0.05) - 吸积盘颜色(橙红)",
        "DistortionStrength (0.12) - 引力透镜扭曲强度",
        "PhotonSphereOffset (0.02) - 光子球距事件视界偏移",
        "PhotonSphereWidth (0.06) - 光子球宽度",
        "PhotonSphereColor (0.3, 0.1, 0.9) - 光子球颜色(紫蓝)",
        "PhotonSphereIntensity (2.5) - 光子球强度",
        "LensingRadius (0.7) - 透镜可视区域半径",
        "RotationSpeed (0.3) - 脉冲动画速度"
    ],
    "effects": [
        "事件视界 - 中心纯黑不透明区域",
        "吸积盘 - 围绕中心的橙红色发光环",
        "光子球 - 紧贴事件视界的薄紫色光环",
        "引力透镜 - 背景扭曲效果(SceneColor采样偏移)",
        "脉冲动画 - 吸积盘亮度随时间脉动",
        "透明渐变 - 从中心到边缘逐渐透明"
    ]
}
