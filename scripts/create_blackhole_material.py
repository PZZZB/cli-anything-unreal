import unreal

EAL = unreal.EditorAssetLibrary
ATH = unreal.AssetToolsHelpers.get_asset_tools()

target_path = "/Game/M_BlackHole"

# Step 1: Create the material asset (safe replacement pattern)
can_create = True
if EAL.does_asset_exist(target_path):
    if EAL.delete_asset(target_path):
        unreal.SystemLibrary.collect_garbage()
    else:
        can_create = False

if not can_create:
    result = {"error": "Failed to delete existing asset", "path": target_path}
else:
    # Create material
    material = ATH.create_asset(
        "M_BlackHole",
        "/Game/",
        unreal.Material,
        unreal.MaterialFactoryNew()
    )

    if not material:
        result = {"error": "Failed to create material asset"}
    else:
        # Set material properties
        # Blend Mode: Translucent (1)
        material.set_editor_property("blend_mode", unreal.BlendMode.BLEND_TRANSLUCENT)
        # Shading Model: Unlit (2)
        material.set_editor_property("shading_model", unreal.MaterialShadingModel.MSM_UNLIT)
        # Two Sided
        material.set_editor_property("two_sided", True)

        # ============================================================
        # Build the Black Hole material node network
        # ============================================================
        # Layout plan (left to right):
        #
        # [Coord] → [RadialDistance] → [1-Dist/Radius] → [Saturate] → [SmoothStep] → Opacity
        #                                    ↓
        #                           [Power] → [Lerp Alpha] → [AccretionColor * Glow] → [Add] → [Add Accretion] → EmissiveColor
        #                                    ↓                    ↑
        #                           [RingMask] → [Power] → Glow   ↑
        #                                                     ↑
        #                           [AccretionColor] ──────────┘
        #
        # [SceneColor] → [Lerp B] (distorted background visible through edge)
        # [Black]      → [Lerp A] (center is pure black)
        #
        # [UV] → [CenterOffset] → [Normalize] → [Scale] → [SceneColor UV offset] → SceneColor lookup

        # Helper to add expression
        def add_expr(expr_class, pos_x=0, pos_y=0, **kwargs):
            expr = unreal.MaterialEditingLibrary.create_material_expression(material, expr_class, pos_x, pos_y)
            for k, v in kwargs.items():
                try:
                    expr.set_editor_property(k, v)
                except Exception as e:
                    unreal.log_warning(f"Could not set {k}={v} on {expr_class}: {e}")
            return expr

        # Helper to connect
        def connect(from_expr, from_output, to_expr, to_input):
            return unreal.MaterialEditingLibrary.connect_material_property(
                from_expr, from_output, to_expr, to_input
            )

        # --- NODE CREATION ---

        # 1. TextureCoordinate - base UVs
        tex_coord = add_expr(unreal.MaterialExpressionTextureCoordinate, pos_x=-1600, pos_y=0)

        # 2. Constant2Vector - Center offset (0.5, 0.5)
        center = add_expr(unreal.MaterialExpressionConstant2Vector, pos_x=-1600, pos_y=200, R=0.5, G=0.5)

        # 3. Subtract - UV - Center
        sub_uv_center = add_expr(unreal.MaterialExpressionSubtract, pos_x=-1400, pos_y=0)

        # 4. Dot product to get radial distance from center
        # Use ComponentMask to split X,Y then remap
        # Actually, let's use a simpler approach: length of (UV - 0.5)
        # We can use a Custom expression for distance, or build it manually

        # Manual distance: (dx*dx + dy*dy) then sqrt
        # Split X and Y
        mask_r = add_expr(unreal.MaterialExpressionComponentMask, pos_x=-1200, pos_y=-100, R=True, G=False, B=False, A=False)
        mask_g = add_expr(unreal.MaterialExpressionComponentMask, pos_x=-1200, pos_y=100, R=False, G=True, B=False, A=False)

        # Multiply each by itself (square)
        square_x = add_expr(unreal.MaterialExpressionMultiply, pos_x=-1000, pos_y=-100)
        square_y = add_expr(unreal.MaterialExpressionMultiply, pos_x=-1000, pos_y=100)

        # Add squared components
        add_sq = add_expr(unreal.MaterialExpressionAdd, pos_x=-800, pos_y=0)

        # Sqrt for distance
        sqrt_dist = add_expr(unreal.MaterialExpressionSquareRoot, pos_x=-600, pos_y=0)

        # 5. OneMinus - invert distance (1 - dist) so center = 1, edge = 0
        one_minus_dist = add_expr(unreal.MaterialExpressionOneMinus, pos_x=-400, pos_y=0)

        # 6. Saturate to clamp 0-1
        saturate = add_expr(unreal.MaterialExpressionSaturate, pos_x=-200, pos_y=0)

        # 7. SmoothStep for clean edge falloff - use a custom approach
        # We'll use Power instead for simplicity
        # Power controls the sharpness of the edge
        edge_power = add_expr(unreal.MaterialExpressionConstant, pos_x=-400, pos_y=200, R=3.0)
        power_opacity = add_expr(unreal.MaterialExpressionPower, pos_x=0, pos_y=0)

        # 8. Second Power for tighter core
        core_power_const = add_expr(unreal.MaterialExpressionConstant, pos_x=0, pos_y=200, R=2.0)
        core_power = add_expr(unreal.MaterialExpressionPower, pos_x=200, pos_y=0)

        # --- Opacity output ---
        # The opacity mask: full opaque at edges, fading to 0 at center
        # Actually for a black hole: center is opaque (event horizon), 
        # and the "lensing edge" is where it becomes transparent
        # So we want: center → opaque, far → transparent
        # The saturate of (1-dist) already gives us center=1, edge=0
        # But we want a specific radius for the event horizon

        # Let's use a different approach with a radius parameter
        # Distance < EventHorizonRadius → fully opaque (black)
        # Distance > EventHorizonRadius → transparent (with distortion glow at edge)

        # Better approach: Create accretion ring and event horizon separately

        # --- EVENT HORIZON (center black disk) ---
        # Scalar: EventHorizonRadius
        eh_radius = add_expr(unreal.MaterialExpressionScalarParameter, pos_x=-600, pos_y=400, 
                              parameter_name="EventHorizonRadius", default_value=0.15)

        # Subtract: dist - EventHorizonRadius
        sub_eh = add_expr(unreal.MaterialExpressionSubtract, pos_x=-400, pos_y=300)

        # Saturate
        saturate_eh = add_expr(unreal.MaterialExpressionSaturate, pos_x=-200, pos_y=300)

        # OneMinus (inside event horizon = 1, outside = 0)  
        oneminus_eh = add_expr(unreal.MaterialExpressionOneMinus, pos_x=0, pos_y=300)

        # This gives us: 1 inside event horizon, 0 outside
        # This will be used as: base opacity (the black center is opaque)

        # --- ACCRETION DISK (glowing ring around event horizon) ---
        # Ring = (dist - InnerRadius) * Scale, then pow and saturate
        accretion_inner = add_expr(unreal.MaterialExpressionScalarParameter, pos_x=-600, pos_y=600,
                                    parameter_name="AccretionInnerRadius", default_value=0.15)
        accretion_outer = add_expr(unreal.MaterialExpressionScalarParameter, pos_x=-600, pos_y=750,
                                    parameter_name="AccretionOuterRadius", default_value=0.5)
        accretion_intensity = add_expr(unreal.MaterialExpressionScalarParameter, pos_x=-600, pos_y=900,
                                        parameter_name="AccretionIntensity", default_value=3.0)

        # Subtract: dist - inner
        sub_acc_inner = add_expr(unreal.MaterialExpressionSubtract, pos_x=-400, pos_y=600)
        # Subtract: outer - inner
        sub_acc_outer = add_expr(unreal.MaterialExpressionSubtract, pos_x=-400, pos_y=750)
        # Divide: (dist - inner) / (outer - inner)
        div_acc = add_expr(unreal.MaterialExpressionDivide, pos_x=-200, pos_y=650)
        # Saturate
        saturate_acc = add_expr(unreal.MaterialExpressionSaturate, pos_x=0, pos_y=650)
        # OneMinus (bright at inner edge, fading outward)
        oneminus_acc = add_expr(unreal.MaterialExpressionOneMinus, pos_x=200, pos_y=650)
        # Power for sharper inner glow
        power_acc = add_expr(unreal.MaterialExpressionPower, pos_x=400, pos_y=650)

        # --- ACCRETION COLOR ---
        # Deep orange/amber color for the accretion disk
        accretion_color = add_expr(unreal.MaterialExpressionVectorParameter, pos_x=200, pos_y=900,
                                    parameter_name="AccretionColor", 
                                    default_value=unreal.LinearColor(r=1.0, g=0.4, b=0.1, a=1.0))

        # Multiply accretion glow * color
        mul_acc_color = add_expr(unreal.MaterialExpressionMultiply, pos_x=600, pos_y=750)

        # Multiply by intensity
        mul_acc_intensity = add_expr(unreal.MaterialExpressionMultiply, pos_x=800, pos_y=750)

        # --- SCENE COLOR for gravitational lensing ---
        # Offset UVs based on direction toward center for distortion
        # Normalize (UV - Center) gives direction
        normalize_dir = add_expr(unreal.MaterialExpressionNormalize, pos_x=-1200, pos_y=300)

        # Distortion strength parameter
        distortion_strength = add_expr(unreal.MaterialExpressionScalarParameter, pos_x=-1000, pos_y=500,
                                        parameter_name="DistortionStrength", default_value=0.15)

        # Multiply direction * strength
        mul_distort = add_expr(unreal.MaterialExpressionMultiply, pos_x=-800, pos_y=400)

        # Subtract from original UV to pull toward center
        sub_distort = add_expr(unreal.MaterialExpressionSubtract, pos_x=-600, pos_y=300)

        # SceneColor with offset UVs
        scene_color = add_expr(unreal.MaterialExpressionSceneColor, pos_x=-400, pos_y=400)

        # --- COMPOSITION ---
        # Add event horizon opacity and accretion glow for final opacity
        # Opacity = event_horizon_mask + accretion_glow (clamped)
        add_opacity = add_expr(unreal.MaterialExpressionAdd, pos_x=600, pos_y=400)

        # Saturate final opacity
        final_opacity = add_expr(unreal.MaterialExpressionSaturate, pos_x=800, pos_y=400)

        # --- EMISSIVE COLOR ---
        # The accretion glow is the only emissive component
        # Black center emits nothing, accretion disk glows

        # --- LERP background with black center ---
        # Lerp between Black (A) and SceneColor (B) using accretion ring as alpha
        # Where event horizon is → Black (not scene color)
        # Where accretion disk is → Accretion color (additive)
        # Where nothing is → Scene color (transparent shows through)

        # Final color = accretion emissive (the ring glows on its own)
        # Background shows through wherever opacity < 1

        # Add a slight purple/blue tint at the photon sphere (just outside event horizon)
        photon_color = add_expr(unreal.MaterialExpressionVectorParameter, pos_x=200, pos_y=1100,
                                 parameter_name="PhotonSphereColor",
                                 default_value=unreal.LinearColor(r=0.3, g=0.1, b=0.8, a=1.0))

        # Photon sphere mask - thin ring just outside event horizon
        photon_offset = add_expr(unreal.MaterialExpressionScalarParameter, pos_x=-600, pos_y=1100,
                                  parameter_name="PhotonSphereOffset", default_value=0.03)
        photon_width = add_expr(unreal.MaterialExpressionScalarParameter, pos_x=-600, pos_y=1250,
                                 parameter_name="PhotonSphereWidth", default_value=0.08)

        # dist - (EventHorizonRadius + Offset)
        add_photon_start = add_expr(unreal.MaterialExpressionAdd, pos_x=-400, pos_y=1100)
        sub_photon = add_expr(unreal.MaterialExpressionSubtract, pos_x=-200, pos_y=1100)
        # Divide by width
        div_photon = add_expr(unreal.MaterialExpressionDivide, pos_x=0, pos_y=1100)
        saturate_photon = add_expr(unreal.MaterialExpressionSaturate, pos_x=200, pos_y=1100)
        oneminus_photon = add_expr(unreal.MaterialExpressionOneMinus, pos_x=400, pos_y=1100)
        power_photon_const = add_expr(unreal.MaterialExpressionConstant, pos_x=400, pos_y=1250, R=5.0)
        power_photon = add_expr(unreal.MaterialExpressionPower, pos_x=600, pos_y=1100)

        # Multiply photon mask * photon color
        mul_photon_color = add_expr(unreal.MaterialExpressionMultiply, pos_x=800, pos_y=1100)

        # Photon intensity
        photon_intensity = add_expr(unreal.MaterialExpressionScalarParameter, pos_x=600, pos_y=1250,
                                     parameter_name="PhotonSphereIntensity", default_value=2.0)
        mul_photon_intensity = add_expr(unreal.MaterialExpressionMultiply, pos_x=1000, pos_y=1100)

        # --- ADD accretion + photon for total emissive ---
        add_emissive = add_expr(unreal.MaterialExpressionAdd, pos_x=1000, pos_y=750)

        # Also add photon to opacity (thin ring visible)
        add_opacity_final = add_expr(unreal.MaterialExpressionAdd, pos_x=1000, pos_y=400)
        final_opacity_sat = add_expr(unreal.MaterialExpressionSaturate, pos_x=1200, pos_y=400)

        # --- Time-based animation for accretion disk ---
        time_expr = add_expr(unreal.MaterialExpressionTime, pos_x=-1600, pos_y=500)
        rot_speed = add_expr(unreal.MaterialExpressionScalarParameter, pos_x=-1400, pos_y=500,
                              parameter_name="RotationSpeed", default_value=0.2)
        mul_time = add_expr(unreal.MaterialExpressionMultiply, pos_x=-1200, pos_y=500)
        # Cosine and Sine for rotation
        cos_rot = add_expr(unreal.MaterialExpressionCosine, pos_x=-1000, pos_y=500)
        sin_rot = add_expr(unreal.MaterialExpressionSine, pos_x=-1000, pos_y=650)

        # We'll modulate the accretion disk with rotation to create swirl effect
        # Use atan2 of (UV-Center) for angular component
        # Instead, let's add simple pulsation to accretion intensity
        # Pulsation = 1 + 0.1 * sin(time * speed)
        pulse_amp = add_expr(unreal.MaterialExpressionConstant, pos_x=-1000, pos_y=800, R=0.15)
        mul_pulse = add_expr(unreal.MaterialExpressionMultiply, pos_x=-800, pos_y=600)
        add_pulse = add_expr(unreal.MaterialExpressionAdd, pos_x=-600, pos_y=600, 
                              # we'll connect Const(1.0) to A
                              )

        # Simple constant 1 for pulse baseline
        const_one = add_expr(unreal.MaterialExpressionConstant, pos_x=-800, pos_y=500, R=1.0)

        # ============================================================
        # CONNECT NODES
        # ============================================================

        # TextureCoordinate → Subtract(A)
        unreal.MaterialEditingLibrary.connect_material_expressions(
            tex_coord, "", sub_uv_center, "A"
        )
        # Center → Subtract(B)
        unreal.MaterialEditingLibrary.connect_material_expressions(
            center, "", sub_uv_center, "B"
        )

        # Subtract → ComponentMask R
        unreal.MaterialEditingLibrary.connect_material_expressions(
            sub_uv_center, "", mask_r, ""
        )
        # Subtract → ComponentMask G
        unreal.MaterialEditingLibrary.connect_material_expressions(
            sub_uv_center, "", mask_g, ""
        )

        # mask_r → Multiply(A) and Multiply(B) (square X)
        unreal.MaterialEditingLibrary.connect_material_expressions(
            mask_r, "", square_x, "A"
        )
        unreal.MaterialEditingLibrary.connect_material_expressions(
            mask_r, "", square_x, "B"
        )

        # mask_g → Multiply(A) and Multiply(B) (square Y)
        unreal.MaterialEditingLibrary.connect_material_expressions(
            mask_g, "", square_y, "A"
        )
        unreal.MaterialEditingLibrary.connect_material_expressions(
            mask_g, "", square_y, "B"
        )

        # square_x → Add(A)
        unreal.MaterialEditingLibrary.connect_material_expressions(
            square_x, "", add_sq, "A"
        )
        # square_y → Add(B)
        unreal.MaterialEditingLibrary.connect_material_expressions(
            square_y, "", add_sq, "B"
        )

        # Add → Sqrt
        unreal.MaterialEditingLibrary.connect_material_expressions(
            add_sq, "", sqrt_dist, ""
        )

        # Sqrt → OneMinus (invert: center=high, edge=low)
        unreal.MaterialEditingLibrary.connect_material_expressions(
            sqrt_dist, "", one_minus_dist, ""
        )

        # OneMinus → Saturate
        unreal.MaterialEditingLibrary.connect_material_expressions(
            one_minus_dist, "", saturate, ""
        )

        # Saturate → Power(Base)
        unreal.MaterialEditingLibrary.connect_material_expressions(
            saturate, "", power_opacity, "Base"
        )
        # edge_power → Power(Exp)
        unreal.MaterialEditingLibrary.connect_material_expressions(
            edge_power, "", power_opacity, "Exponent"
        )

        # Power → Power2(Base) for tighter falloff
        unreal.MaterialEditingLibrary.connect_material_expressions(
            power_opacity, "", core_power, "Base"
        )
        # core_power_const → Power2(Exp)
        unreal.MaterialEditingLibrary.connect_material_expressions(
            core_power_const, "", core_power, "Exponent"
        )

        # ---- Event Horizon ----
        # sqrt_dist → Subtract_eh(A)
        unreal.MaterialEditingLibrary.connect_material_expressions(
            sqrt_dist, "", sub_eh, "A"
        )
        # eh_radius → Subtract_eh(B)
        unreal.MaterialEditingLibrary.connect_material_expressions(
            eh_radius, "", sub_eh, "B"
        )

        # sub_eh → Saturate_eh
        unreal.MaterialEditingLibrary.connect_material_expressions(
            sub_eh, "", saturate_eh, ""
        )

        # saturate_eh → OneMinus_eh (inside = 1, outside = 0)
        unreal.MaterialEditingLibrary.connect_material_expressions(
            saturate_eh, "", oneminus_eh, ""
        )

        # ---- Accretion Disk ----
        # sqrt_dist → sub_acc_inner(A)
        unreal.MaterialEditingLibrary.connect_material_expressions(
            sqrt_dist, "", sub_acc_inner, "A"
        )
        # accretion_inner → sub_acc_inner(B)
        unreal.MaterialEditingLibrary.connect_material_expressions(
            accretion_inner, "", sub_acc_inner, "B"
        )

        # accretion_outer → sub_acc_outer(A)
        unreal.MaterialEditingLibrary.connect_material_expressions(
            accretion_outer, "", sub_acc_outer, "A"
        )
        # accretion_inner → sub_acc_outer(B)
        unreal.MaterialEditingLibrary.connect_material_expressions(
            accretion_inner, "", sub_acc_outer, "B"
        )

        # sub_acc_inner → div_acc(A)
        unreal.MaterialEditingLibrary.connect_material_expressions(
            sub_acc_inner, "", div_acc, "A"
        )
        # sub_acc_outer → div_acc(B)
        unreal.MaterialEditingLibrary.connect_material_expressions(
            sub_acc_outer, "", div_acc, "B"
        )

        # div_acc → saturate_acc
        unreal.MaterialEditingLibrary.connect_material_expressions(
            div_acc, "", saturate_acc, ""
        )

        # saturate_acc → oneminus_acc (bright at inner, dim at outer)
        unreal.MaterialEditingLibrary.connect_material_expressions(
            saturate_acc, "", oneminus_acc, ""
        )

        # oneminus_acc → power_acc(Base)
        unreal.MaterialEditingLibrary.connect_material_expressions(
            oneminus_acc, "", power_acc, "Base"
        )
        # accretion_intensity → power_acc(Exponent) - using intensity as power for glow sharpness
        unreal.MaterialEditingLibrary.connect_material_expressions(
            accretion_intensity, "", power_acc, "Exponent"
        )

        # power_acc → mul_acc_color(A)
        unreal.MaterialEditingLibrary.connect_material_expressions(
            power_acc, "", mul_acc_color, "A"
        )
        # accretion_color → mul_acc_color(B)
        unreal.MaterialEditingLibrary.connect_material_expressions(
            accretion_color, "", mul_acc_color, "B"
        )

        # mul_acc_color → mul_acc_intensity(A)
        unreal.MaterialEditingLibrary.connect_material_expressions(
            mul_acc_color, "", mul_acc_intensity, "A"
        )
        # accretion_intensity → mul_acc_intensity(B)
        unreal.MaterialEditingLibrary.connect_material_expressions(
            accretion_intensity, "", mul_acc_intensity, "B"
        )

        # ---- Scene Color (Gravitational Lensing) ----
        # sub_uv_center → normalize_dir
        unreal.MaterialEditingLibrary.connect_material_expressions(
            sub_uv_center, "", normalize_dir, ""
        )

        # normalize_dir → mul_distort(A)
        unreal.MaterialEditingLibrary.connect_material_expressions(
            normalize_dir, "", mul_distort, "A"
        )
        # distortion_strength → mul_distort(B)
        unreal.MaterialEditingLibrary.connect_material_expressions(
            distortion_strength, "", mul_distort, "B"
        )

        # tex_coord → sub_distort(A)
        unreal.MaterialEditingLibrary.connect_material_expressions(
            tex_coord, "", sub_distort, "A"
        )
        # mul_distort → sub_distort(B) (pull UVs toward center)
        unreal.MaterialEditingLibrary.connect_material_expressions(
            mul_distort, "", sub_distort, "B"
        )

        # sub_distort → scene_color(Coordinates)
        unreal.MaterialEditingLibrary.connect_material_expressions(
            sub_distort, "", scene_color, "Coordinates"
        )

        # ---- Photon Sphere ----
        # eh_radius → add_photon_start(A)
        unreal.MaterialEditingLibrary.connect_material_expressions(
            eh_radius, "", add_photon_start, "A"
        )
        # photon_offset → add_photon_start(B)
        unreal.MaterialEditingLibrary.connect_material_expressions(
            photon_offset, "", add_photon_start, "B"
        )

        # sqrt_dist → sub_photon(A)
        unreal.MaterialEditingLibrary.connect_material_expressions(
            sqrt_dist, "", sub_photon, "A"
        )
        # add_photon_start → sub_photon(B)
        unreal.MaterialEditingLibrary.connect_material_expressions(
            add_photon_start, "", sub_photon, "B"
        )

        # sub_photon → div_photon(A)
        unreal.MaterialEditingLibrary.connect_material_expressions(
            sub_photon, "", div_photon, "A"
        )
        # photon_width → div_photon(B)
        unreal.MaterialEditingLibrary.connect_material_expressions(
            photon_width, "", div_photon, "B"
        )

        # div_photon → saturate_photon
        unreal.MaterialEditingLibrary.connect_material_expressions(
            div_photon, "", saturate_photon, ""
        )

        # saturate_photon → oneminus_photon
        unreal.MaterialEditingLibrary.connect_material_expressions(
            saturate_photon, "", oneminus_photon, ""
        )

        # oneminus_photon → power_photon(Base)
        unreal.MaterialEditingLibrary.connect_material_expressions(
            oneminus_photon, "", power_photon, "Base"
        )
        # power_photon_const → power_photon(Exponent)
        unreal.MaterialEditingLibrary.connect_material_expressions(
            power_photon_const, "", power_photon, "Exponent"
        )

        # power_photon → mul_photon_color(A)
        unreal.MaterialEditingLibrary.connect_material_expressions(
            power_photon, "", mul_photon_color, "A"
        )
        # photon_color → mul_photon_color(B)
        unreal.MaterialEditingLibrary.connect_material_expressions(
            photon_color, "", mul_photon_color, "B"
        )

        # mul_photon_color → mul_photon_intensity(A)
        unreal.MaterialEditingLibrary.connect_material_expressions(
            mul_photon_color, "", mul_photon_intensity, "A"
        )
        # photon_intensity → mul_photon_intensity(B)
        unreal.MaterialEditingLibrary.connect_material_expressions(
            photon_intensity, "", mul_photon_intensity, "B"
        )

        # ---- Pulse animation for accretion ----
        # time → mul_time(A)
        unreal.MaterialEditingLibrary.connect_material_expressions(
            time_expr, "", mul_time, "A"
        )
        # rot_speed → mul_time(B)
        unreal.MaterialEditingLibrary.connect_material_expressions(
            rot_speed, "", mul_time, "B"
        )

        # mul_time → sin_rot
        unreal.MaterialEditingLibrary.connect_material_expressions(
            mul_time, "", sin_rot, ""
        )

        # sin_rot → mul_pulse(A)
        unreal.MaterialEditingLibrary.connect_material_expressions(
            sin_rot, "", mul_pulse, "A"
        )
        # pulse_amp → mul_pulse(B)
        unreal.MaterialEditingLibrary.connect_material_expressions(
            pulse_amp, "", mul_pulse, "B"
        )

        # const_one → add_pulse(A)
        unreal.MaterialEditingLibrary.connect_material_expressions(
            const_one, "", add_pulse, "A"
        )
        # mul_pulse → add_pulse(B)
        unreal.MaterialEditingLibrary.connect_material_expressions(
            mul_pulse, "", add_pulse, "B"
        )

        # add_pulse → mul_acc_intensity(B) - modulate accretion with pulse
        # Actually, let's insert pulse between mul_acc_color and mul_acc_intensity
        # We need to reconnect: mul_acc_color → pulse_multiply → mul_acc_intensity
        # Instead, let's just multiply the accretion output by the pulse
        # We'll insert a multiply before mul_acc_intensity

        # Create a new multiply for pulse modulation
        pulse_mod = add_expr(unreal.MaterialExpressionMultiply, pos_x=700, pos_y=650)
        
        # mul_acc_color → pulse_mod(A)
        unreal.MaterialEditingLibrary.connect_material_expressions(
            mul_acc_color, "", pulse_mod, "A"
        )
        # add_pulse → pulse_mod(B)
        unreal.MaterialEditingLibrary.connect_material_expressions(
            add_pulse, "", pulse_mod, "B"
        )

        # pulse_mod → mul_acc_intensity(A) - reconnect
        unreal.MaterialEditingLibrary.connect_material_expressions(
            pulse_mod, "", mul_acc_intensity, "A"
        )

        # ---- Final Composition ----
        # Opacity: event_horizon_mask + accretion_glow + photon_glow
        # oneminus_eh → add_opacity(A)
        unreal.MaterialEditingLibrary.connect_material_expressions(
            oneminus_eh, "", add_opacity, "A"
        )
        # power_acc → add_opacity(B) (accretion ring adds opacity)
        unreal.MaterialEditingLibrary.connect_material_expressions(
            power_acc, "", add_opacity, "B"
        )

        # add_opacity → add_opacity_final(A)
        unreal.MaterialEditingLibrary.connect_material_expressions(
            add_opacity, "", add_opacity_final, "A"
        )
        # power_photon → add_opacity_final(B)
        unreal.MaterialEditingLibrary.connect_material_expressions(
            power_photon, "", add_opacity_final, "B"
        )

        # add_opacity_final → final_opacity_sat
        unreal.MaterialEditingLibrary.connect_material_expressions(
            add_opacity_final, "", final_opacity_sat, ""
        )

        # Emissive: accretion_glow + photon_glow
        # mul_acc_intensity → add_emissive(A)
        unreal.MaterialEditingLibrary.connect_material_expressions(
            mul_acc_intensity, "", add_emissive, "A"
        )
        # mul_photon_intensity → add_emissive(B)
        unreal.MaterialEditingLibrary.connect_material_expressions(
            mul_photon_intensity, "", add_emissive, "B"
        )

        # ---- Connect to Material Outputs ----
        # Emissive Color
        unreal.MaterialEditingLibrary.connect_material_property(
            add_emissive, "", unreal.MaterialProperty.MP_EMISSIVE_COLOR
        )

        # Opacity
        unreal.MaterialEditingLibrary.connect_material_property(
            final_opacity_sat, "", unreal.MaterialProperty.MP_OPACITY
        )

        # ---- Add comment nodes for organization ----
        comment_eh = add_expr(unreal.MaterialExpressionComment, pos_x=-700, pos_y=250, 
                               comment_text="Event Horizon", size_x=500, size_y=200)
        comment_acc = add_expr(unreal.MaterialExpressionComment, pos_x=-700, pos_y=550,
                                comment_text="Accretion Disk", size_x=1500, size_y=500)
        comment_photon = add_expr(unreal.MaterialExpressionComment, pos_x=-700, pos_y=1050,
                                   comment_text="Photon Sphere", size_x=1500, size_y=400)
        comment_distort = add_expr(unreal.MaterialExpressionComment, pos_x=-1700, pos_y=250,
                                    comment_text="Gravitational Lensing", size_x=1400, size_y=350)
        comment_anim = add_expr(unreal.MaterialExpressionComment, pos_x=-1700, pos_y=450,
                                 comment_text="Pulse Animation", size_x=1100, size_y=400)

        # Let material know it needs SceneColor
        material.set_editor_property("blend_mode", unreal.BlendMode.BLEND_TRANSLUCENT)

        # Recompile
        unreal.MaterialEditingLibrary.recompile_material(material)

        result = {
            "status": "ok",
            "path": target_path,
            "material": material.get_name(),
            "blend_mode": "Translucent",
            "shading_model": "Unlit",
            "parameters": [
                "EventHorizonRadius",
                "AccretionInnerRadius", 
                "AccretionOuterRadius",
                "AccretionIntensity",
                "AccretionColor",
                "DistortionStrength",
                "PhotonSphereOffset",
                "PhotonSphereWidth",
                "PhotonSphereColor",
                "PhotonSphereIntensity",
                "RotationSpeed"
            ]
        }
