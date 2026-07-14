#pragma once

#include "CoreMinimal.h"
#include "Kismet/BlueprintFunctionLibrary.h"
#include "UObject/UnrealType.h"
#include "CliAnythingBridgeLibrary.generated.h"

class UMaterial;
class UMaterialExpression;
class UMaterialInterface;
class UTexture2D;
class UScriptStruct;
class UWidgetBlueprint;

UCLASS()
class CLIANYTHINGBRIDGE_API UCliAnythingBridgeLibrary : public UBlueprintFunctionLibrary
{
	GENERATED_BODY()

public:
	/**
	 * Returns the current compile errors for a material, directly from
	 * FMaterialResource::GetCompileErrors(). Unlike log-based approaches,
	 * this reflects the exact current state regardless of shader cache.
	 */
	UFUNCTION(BlueprintCallable, Category = "CliAnything")
	static TArray<FString> GetMaterialCompileErrors(UMaterialInterface* Material);

	/**
	 * Disconnects a material expression input pin.
	 * UE Python exposes ConnectMaterialExpressions but no reliable disconnect API,
	 * and FExpressionInput properties are protected from Python.
	 * Returns a JSON result string.
	 */
	UFUNCTION(BlueprintCallable, Category = "CliAnything")
	static FString DisconnectMaterialExpressionInput(UMaterial* Material, UMaterialExpression* ToExpression, const FString& ToInputName);

	/**
	 * Gets the absolute screen coordinates (X, Y, Width, Height) of the active level viewport.
	 * If no viewport is active or found, returns all zeros.
	 * Allows Python scripts to crop a full-screen screenshot to just the viewport.
	 */
	UFUNCTION(BlueprintCallable, Category = "CliAnything")
	static FIntVector4 GetActiveViewportScreenBounds();

	/**
	 * Redraws the active Level Viewport and synchronously writes a PNG.
	 * Unlike HighResShot, this targets one viewport and preserves its live state.
	 */
	UFUNCTION(BlueprintCallable, Category = "CliAnything")
	static bool TakeActiveViewportScreenshot(const FString& OutputPath);

	/**
	 * Gets recent engine error and warning logs.
	 */
	UFUNCTION(BlueprintCallable, Category = "CliAnything")
	static TArray<FString> GetRecentEngineErrors(int32 Count = 10);

	/**
	 * Returns the plugin version string (from .uplugin VersionName).
	 * Used to detect version mismatches between the running plugin and the bundled source.
	 */
	UFUNCTION(BlueprintCallable, Category = "CliAnything")
	static FString GetPluginVersion();

	/**
	 * Returns JSON metadata for a console variable, including whether it exists.
	 * This disambiguates missing CVars from real string CVars with empty values.
	 */
	UFUNCTION(BlueprintCallable, Category = "CliAnything")
	static FString GetConsoleVariableInfo(const FString& Name);

	/**
	 * Returns JSON TextureSource metadata for a Texture2D.
	 * UE Python exposes UTexture2D but not Texture->Source, so SDF/UI
	 * validation that needs source size/format/channel stats goes through C++.
	 */
	UFUNCTION(BlueprintCallable, Category = "CliAnything")
	static FString GetTextureSourceInfo(UTexture2D* Texture);

	/**
	 * Writes the material's translated HLSL code to a file (equivalent to Window > HLSL Code).
	 * Calls FMaterial::GetMaterialExpressionSource() which triggers the material translator.
	 * This is lightweight — no shader dump or RecompileShaders needed.
	 * Returns: single-element array ["FILE_PATH"] on success, empty on failure.
	 */
	UFUNCTION(BlueprintCallable, Category = "CliAnything")
	static TArray<FString> GetMaterialHLSLCode(UMaterialInterface* Material, const FString& OutputPath);

	/**
	 * Writes the full preprocessed shader source for all compiled shaders of a material
	 * to separate .usf files in the specified output directory.
	 * Each file is named by shader type (e.g., TBasePassPSFNoLightMapPolicy.usf).
	 * Returns: array of "SHADER_NAME\tFILE_PATH\tLINE_COUNT" for each shader written.
	 * The source contains complete cbuffer/struct definitions (View, Primitive, etc.).
	 * Requires the material to have been compiled at least once (e.g., opened in material editor).
	 */
	UFUNCTION(BlueprintCallable, Category = "CliAnything")
	static TArray<FString> GetMaterialShaderSource(UMaterialInterface* Material, const FString& OutputDir);

	/**
	 * Returns complete reflection info for a UE class, using TFieldIterator (same system
	 * the Details panel uses). Returns JSON string with two arrays:
	 *   "properties": [{name, type, flags, category, tooltip}, ...]
	 *   "functions":  [{name, flags, return_type, params:[{name,type}], tooltip}, ...]
	 *
	 * @param ClassName  UE class name (e.g., "MaterialExpressionConstant3Vector")
	 * @param bIncludeInherited  If true, includes properties/functions from parent classes
	 * @return JSON string with reflection data, or empty string if class not found
	 */
	UFUNCTION(BlueprintCallable, Category = "CliAnything")
	static FString GetClassInfo(const FString& ClassName, bool bIncludeInherited = true);

	/**
	 * Returns reflected UScriptStruct properties as JSON.
	 * Used for UE Python structs such as CustomInput that are not UClass types.
	 */
	UFUNCTION(BlueprintCallable, Category = "CliAnything")
	static FString GetStructInfo(UScriptStruct* Struct, bool bIncludeInherited = true);

	/**
	 * Returns the component tree of an Actor, mirroring what a user sees in the Details
	 * panel's Components section after selecting the Actor in World Outliner.
	 *
	 * By default, editor-only visualization components (arrow gizmos, billboard icons,
	 * text renderers for debug display) are filtered out — same as the SCS Components
	 * tree does. Pass bIncludeVisualization=true to see every UActorComponent returned
	 * by AActor::GetComponents().
	 *
	 * For each component returns:
	 *   name, class, path (full object path), is_root, is_native, parent (attach parent name)
	 *
	 * The returned "path" can be passed directly to Remote Control /object/property or to
	 * CLI commands (api-discover, scene property) without any path massaging.
	 *
	 * @param Actor                   The Actor to inspect.
	 * @param bIncludeVisualization   If true, include UActorComponent::IsVisualizationComponent()
	 *                                components (default false to match Details panel).
	 * @return JSON array string: [{name,class,path,is_root,is_native,parent}, ...]
	 *         Empty array "[]" if Actor is null or has no components.
	 */
	UFUNCTION(BlueprintCallable, Category = "CliAnything")
	static FString GetActorComponentTree(AActor* Actor, bool bIncludeVisualization = false);

	/**
	 * Sets the design-time root widget for a Widget Blueprint.
	 * Python cannot access WidgetTree::RootWidget because it is protected by the
	 * generated reflection wrapper, so UMG authoring goes through this bridge.
	 */
	UFUNCTION(BlueprintCallable, Category = "CliAnything|UMG")
	static FString SetWidgetBlueprintRoot(UWidgetBlueprint* Blueprint, const FString& RootWidgetClassName, const FString& RootWidgetName, bool bIsVariable);

	/**
	 * Adds a widget under a CanvasPanel in a Widget Blueprint, sets Canvas slot layout,
	 * and optionally marks it as a Blueprint variable.
	 */
	UFUNCTION(BlueprintCallable, Category = "CliAnything|UMG")
	static FString AddWidgetToCanvas(UWidgetBlueprint* Blueprint, const FString& WidgetClassName, const FString& WidgetName, const FString& ParentWidgetName, bool bIsVariable, float X, float Y, float Width, float Height, int32 ZOrder, const FString& Text);

	/**
	 * Edits an existing UMG Image widget's brush resource and CanvasPanelSlot.
	 * Python cannot reliably read WidgetBlueprint.WidgetTree because it is protected.
	 */
	UFUNCTION(BlueprintCallable, Category = "CliAnything|UMG")
	static FString SetWidgetImageProperties(UWidgetBlueprint* Blueprint, const FString& WidgetName, UObject* ResourceObject, bool bSetResource, bool bSetPosition, float X, float Y, bool bSetSize, float Width, float Height, bool bSetZOrder, int32 ZOrder, bool bSetBrushImageSize = false, float ImageWidth = 0.0f, float ImageHeight = 0.0f);

	/**
	 * Returns the design-time WidgetTree as JSON, including root, widgets, parent,
	 * CanvasPanel slot layout, and TextBlock text when present.
	 */
	UFUNCTION(BlueprintCallable, Category = "CliAnything|UMG")
	static FString GetWidgetBlueprintTree(UWidgetBlueprint* Blueprint);
};
