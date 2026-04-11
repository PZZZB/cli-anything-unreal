import unreal

EAL = unreal.EditorAssetLibrary

target_path = "/Game/M_BlackHole"

# Load the existing material
material = EAL.load_asset(target_path)
if not material:
    result = {"error": "Could not load material"}
else:
    # First, let's delete the orphan nodes that aren't contributing
    # Then reconnect SceneColor into the emissive chain
    
    # Orphan nodes to delete:
    # - Comment nodes (useless without text)
    # - Unused constant/power/saturate nodes from the initial radial gradient attempt
    # - The Cosine node (not connected)
    
    orphans_to_delete = [
        "MaterialExpressionComment_0",
        "MaterialExpressionComment_1", 
        "MaterialExpressionComment_2",
        "MaterialExpressionComment_3",
        "MaterialExpressionComment_4",
        "MaterialExpressionConstant_0",  # was edge_power for old opacity approach
        "MaterialExpressionConstant_1",  # was core_power_const
        "MaterialExpressionConstant_2",  # was power_photon_const (already connected via different path)
        "MaterialExpressionPower_0",     # was power_opacity (old opacity approach)
        "MaterialExpressionPower_1",     # was core_power (old opacity approach)
        "MaterialExpressionSaturate_0",  # old saturate
        "MaterialExpressionOneMinus_0",  # old one_minus_dist
        "MaterialExpressionSaturate_3",  # another unused saturate
        "MaterialExpressionCosine_0",    # cosine not used (we used sine)
    ]

    # Delete orphan nodes
    deleted = []
    failed = []
    for node_name in orphans_to_delete:
        try:
            expr = None
            # Find expression by iterating material expressions
            # We need to use find_material_expression
            expr = unreal.MaterialEditingLibrary.find_material_expression(material, node_name)
            if expr:
                unreal.MaterialEditingLibrary.delete_material_expression(material, expr)
                deleted.append(node_name)
            else:
                failed.append(f"{node_name}: not found")
        except Exception as e:
            failed.append(f"{node_name}: {e}")

    # Now we need to integrate SceneColor into the emissive output
    # Current emissive: accretion_glow + photon_glow
    # We want: Lerp(SceneColor, AccretionGlow+PhotonGlow, AccretionAndPhotonMask)
    # This way the background shows through where there's no glow, 
    # and the accretion/photon sphere overrides it
    
    # The SceneColor node (MaterialExpressionSceneColor_0) is already created
    # It's connected to Subtract_4 (distorted UVs) which is connected to Normalize_0
    # But none of these are connected to the output
    
    # Let's reconnect SceneColor into the material
    
    # Find existing nodes
    scene_color = unreal.MaterialEditingLibrary.find_material_expression(material, "MaterialExpressionSceneColor_0")
    subtract_4 = unreal.MaterialEditingLibrary.find_material_expression(material, "MaterialExpressionSubtract_4")
    multiply_4 = unreal.MaterialEditingLibrary.find_material_expression(material, "MaterialExpressionMultiply_4")
    normalize_0 = unreal.MaterialEditingLibrary.find_material_expression(material, "MaterialExpressionNormalize_0")
    scalar_param_4 = unreal.MaterialEditingLibrary.find_material_expression(material, "MaterialExpressionScalarParameter_4")
    
    # The current Add_3 is the emissive output
    # We need to add SceneColor to it as a base
    # Create a Lerp: A=SceneColor, B=CurrentEmissive, Alpha=opacity_mask
    
    # Actually, in Unlit+Translucent mode, the Emissive Color IS what gets rendered
    # and Opacity controls how much it blends with the background
    # So the SceneColor will naturally show through wherever Opacity < 1
    # 
    # But we need to ensure the distorted background is actually visible
    # In Unlit+Translucent, the background IS the scene color behind the object
    # The distortion effect works by modifying the pixel offset (SceneColor node samples)
    # but this needs to be fed into a different channel
    
    # For gravitational lensing with SceneColor in Translucent material:
    # We need to output the distorted SceneColor as the base emissive color
    # Then add the accretion/photon glow on top
    
    # Create a Lerp between SceneColor (distorted) and AccretionEmissive
    # using the total glow as alpha (where there's glow, use accretion color; 
    # where there isn't, use distorted scene color)
    
    # But wait - in Translucent Unlit, the opacity already handles blending
    # The issue is: we want the ENTIRE area (event horizon + accretion + lensing edge)
    # to have some opacity, and the emissive color should show:
    # - Black in the event horizon (but scene color around it gets distorted)
    # - Accretion glow in the ring
    # - Distorted scene color in the lensing zone
    
    # Better approach: 
    # EmissiveColor = Lerp(SceneColor, AccretionEmissive, GlowMask)
    # Opacity = EventHorizonMask + LensingEdgeMask + AccretionMask + PhotonMask
    
    # Let me add a LensingEdge mask and connect SceneColor properly
    
    # Add Lerp node
    lerp_color = unreal.MaterialEditingLibrary.create_material_expression(
        material, unreal.MaterialExpressionLinearInterpolate, 1000, 0
    )
    
    # Add a lensing edge mask (ring outside event horizon where distortion is visible)
    # This is basically: smooth falloff outside event horizon
    # dist > EventHorizonRadius → gradually fading to 0
    lensing_radius = unreal.MaterialEditingLibrary.create_material_expression(
        material, unreal.MaterialExpressionScalarParameter, -600, 1400
    )
    lensing_radius.set_editor_property("parameter_name", "LensingRadius")
    lensing_radius.set_editor_property("default_value", 0.8)
    
    # sqrt_dist is MaterialExpressionSquareRoot_0
    sqrt_dist = unreal.MaterialEditingLibrary.find_material_expression(material, "MaterialExpressionSquareRoot_0")
    
    # dist / LensingRadius
    div_lens = unreal.MaterialEditingLibrary.create_material_expression(
        material, unreal.MaterialExpressionDivide, -400, 1400
    )
    
    # Saturate
    sat_lens = unreal.MaterialEditingLibrary.create_material_expression(
        material, unreal.MaterialExpressionSaturate, -200, 1400
    )
    
    # OneMinus (close to center = 1, far = 0)
    oneminus_lens = unreal.MaterialEditingLibrary.create_material_expression(
        material, unreal.MaterialExpressionOneMinus, 0, 1400
    )
    
    # Connect: sqrt_dist → div_lens(A), lensing_radius → div_lens(B)
    unreal.MaterialEditingLibrary.connect_material_expressions(sqrt_dist, "", div_lens, "A")
    unreal.MaterialEditingLibrary.connect_material_expressions(lensing_radius, "", div_lens, "B")
    
    # div_lens → sat_lens → oneminus_lens
    unreal.MaterialEditingLibrary.connect_material_expressions(div_lens, "", sat_lens, "")
    unreal.MaterialEditingLibrary.connect_material_expressions(sat_lens, "", oneminus_lens, "")
    
    # Add this lensing mask to the opacity
    # Current opacity chain: add_opacity_final → final_opacity_sat → MP_OPACITY
    # We need to add lensing mask to add_opacity_final
    
    # Find existing nodes
    add_opacity_final = unreal.MaterialEditingLibrary.find_material_expression(material, "MaterialExpressionAdd_4")
    final_opacity_sat = unreal.MaterialEditingLibrary.find_material_expression(material, "MaterialExpressionSaturate_5")
    
    # Disconnect current output from Add_4 to Saturate_5
    # We need to insert a new Add between them
    add_lens_opacity = unreal.MaterialEditingLibrary.create_material_expression(
        material, unreal.MaterialExpressionAdd, 1100, 400
    )
    
    # Connect: add_opacity_final → add_lens_opacity(A)
    unreal.MaterialEditingLibrary.connect_material_expressions(add_opacity_final, "", add_lens_opacity, "A")
    # Connect: oneminus_lens → add_lens_opacity(B)
    unreal.MaterialEditingLibrary.connect_material_expressions(oneminus_lens, "", add_lens_opacity, "B")
    
    # Reconnect: add_lens_opacity → final_opacity_sat
    # First disconnect the old connection
    unreal.MaterialEditingLibrary.disconnect_material_property(unreal.MaterialProperty.MP_OPACITY)
    
    # Connect new chain
    unreal.MaterialEditingLibrary.connect_material_expressions(add_lens_opacity, "", final_opacity_sat, "")
    unreal.MaterialEditingLibrary.connect_material_property(final_opacity_sat, "", unreal.MaterialProperty.MP_OPACITY)
    
    # Now connect SceneColor into the emissive chain
    # Current: add_emissive (Add_3) → MP_EMISSIVE_COLOR
    # New: Lerp(SceneColor, add_emissive, glow_mask) → MP_EMISSIVE_COLOR
    
    add_emissive = unreal.MaterialEditingLibrary.find_material_expression(material, "MaterialExpressionAdd_3")
    
    # Create a combined glow mask for the lerp alpha
    # The glow mask = accretion intensity (power_acc = Power_2)
    power_acc = unreal.MaterialEditingLibrary.find_material_expression(material, "MaterialExpressionPower_2")
    
    # Saturate the glow mask
    sat_glow = unreal.MaterialEditingLibrary.create_material_expression(
        material, unreal.MaterialExpressionSaturate, 900, 200
    )
    unreal.MaterialEditingLibrary.connect_material_expressions(power_acc, "", sat_glow, "")
    
    # Lerp: A=SceneColor, B=add_emissive, Alpha=glow_mask
    unreal.MaterialEditingLibrary.connect_material_expressions(scene_color, "", lerp_color, "A")
    unreal.MaterialEditingLibrary.connect_material_expressions(add_emissive, "", lerp_color, "B")
    unreal.MaterialEditingLibrary.connect_material_expressions(sat_glow, "", lerp_color, "Alpha")
    
    # Disconnect old emissive and connect new
    unreal.MaterialEditingLibrary.disconnect_material_property(unreal.MaterialProperty.MP_EMISSIVE_COLOR)
    unreal.MaterialEditingLibrary.connect_material_property(lerp_color, "", unreal.MaterialProperty.MP_EMISSIVE_COLOR)
    
    # Recompile
    unreal.MaterialEditingLibrary.recompile_material(material)
    
    result = {
        "status": "ok",
        "deleted_orphans": deleted,
        "failed_deletions": failed,
        "changes": [
            "Added LensingRadius parameter for lensing zone",
            "Connected SceneColor (distorted) as base emissive",
            "Added Lerp(SceneColor, Glow, GlowMask) for emissive output",
            "Added lensing mask to opacity chain",
            "Cleaned up unused orphan nodes"
        ]
    }
