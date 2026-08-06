#include "CliAnythingBridgeLibrary.h"

#include "Materials/Material.h"
#include "Materials/MaterialExpression.h"
#include "Materials/MaterialInterface.h"
#include "MaterialEditingLibrary.h"
#include "Engine/Engine.h"
#include "Engine/Texture2D.h"
#include "Engine/Texture.h"
#include "MaterialShared.h"
#include "RHI.h"
#include "ShaderCompiler.h"
#include "ShaderCompilerCore.h"

#include "LevelEditor.h"
#include "SLevelViewport.h"
#include "Modules/ModuleManager.h"
#include "Framework/Application/SlateApplication.h"
#include "HAL/CriticalSection.h"
#include "HAL/FileManager.h"
#include "HAL/IConsoleManager.h"
#include "ImageUtils.h"
#include "Misc/FileHelper.h"
#include "Misc/Paths.h"
#include "RenderingThread.h"
#include "Runtime/Launch/Resources/Version.h"
#include "Slate/SceneViewport.h"

#include "GameFramework/Actor.h"
#include "Components/ActorComponent.h"
#include "Components/SceneComponent.h"
#include "Blueprint/WidgetTree.h"
#include "Components/CanvasPanel.h"
#include "Components/CanvasPanelSlot.h"
#include "Components/PanelWidget.h"
#include "Components/TextBlock.h"
#include "Components/Image.h"
#include "Components/Widget.h"
#include "Kismet2/BlueprintEditorUtils.h"
#include "WidgetBlueprint.h"

#include "UObject/UnrealType.h"
#include "UObject/UObjectIterator.h"
#include "UObject/TextProperty.h"

static FString JsonEscape(const FString& Input);
static FString JsonError(const FString& Message);
static FString JsonStringArray(const TArray<FString>& Values);
static UClass* FindWidgetClassByName(const FString& ClassName);
static FString WidgetJson(UWidget* Widget, UWidgetBlueprint* Blueprint);

class FMaterialResourceExtractSource : public FMaterialResource
{
public:
#if ENGINE_MAJOR_VERSION >= 5
	virtual void SetupExtraCompilationSettings(FExtraShaderCompilerSettings& Settings) const override
#else
	virtual void SetupExtaCompilationSettings(const EShaderPlatform Platform, FExtraShaderCompilerSettings& Settings) const override
#endif
	{
		Settings.bExtractShaderSource = true;
	}
};

#if ENGINE_MAJOR_VERSION < 5
static const TCHAR* GetTextureSourceFormatName426(ETextureSourceFormat Format)
{
	switch (Format)
	{
	case TSF_G8: return TEXT("TSF_G8");
	case TSF_BGRA8: return TEXT("TSF_BGRA8");
	case TSF_BGRE8: return TEXT("TSF_BGRE8");
	case TSF_RGBA16: return TEXT("TSF_RGBA16");
	case TSF_RGBA16F: return TEXT("TSF_RGBA16F");
	case TSF_RGBA8: return TEXT("TSF_RGBA8");
	case TSF_RGBE8: return TEXT("TSF_RGBE8");
	case TSF_G16: return TEXT("TSF_G16");
	default: return TEXT("TSF_Invalid");
	}
}

static int32 GetTextureSourceNumComponents426(ETextureSourceFormat Format)
{
	switch (Format)
	{
	case TSF_G8:
	case TSF_G16:
		return 1;
	case TSF_BGRA8:
	case TSF_BGRE8:
	case TSF_RGBA16:
	case TSF_RGBA16F:
	case TSF_RGBA8:
	case TSF_RGBE8:
		return 4;
	default:
		return 0;
	}
}
#endif

TArray<FString> UCliAnythingBridgeLibrary::GetMaterialCompileErrors(UMaterialInterface* Material)
{
	TArray<FString> Result;
	if (!Material) return Result;
	UMaterial* BaseMat = Material->GetMaterial();
	if (!BaseMat) return Result;
	const EShaderPlatform Platform = GMaxRHIShaderPlatform;
	for (int32 QualityLevel = 0; QualityLevel < EMaterialQualityLevel::Num; ++QualityLevel)
	{
#if ENGINE_MAJOR_VERSION >= 5
		const FMaterialResource* Resource = BaseMat->GetMaterialResource(Platform, static_cast<EMaterialQualityLevel::Type>(QualityLevel));
#else
		const FMaterialResource* Resource = BaseMat->GetMaterialResource(GMaxRHIFeatureLevel, static_cast<EMaterialQualityLevel::Type>(QualityLevel));
#endif
		if (!Resource) continue;
		for (const FString& Error : Resource->GetCompileErrors()) { Result.AddUnique(Error); }
	}
	return Result;
}

FString UCliAnythingBridgeLibrary::DisconnectMaterialExpressionInput(UMaterial* Material, UMaterialExpression* ToExpression, const FString& ToInputName)
{
	if (!Material)
	{
		return JsonError(TEXT("Material is null"));
	}
	if (!ToExpression)
	{
		return JsonError(TEXT("Target expression is null"));
	}

	FString Wanted = ToInputName;
	Wanted.TrimStartAndEndInline();

	TArray<FString> AvailableInputs;
	int32 TargetIndex = INDEX_NONE;
	FExpressionInput* TargetInput = nullptr;
	for (int32 Index = 0;; ++Index)
	{
		FExpressionInput* CurrentInput = ToExpression->GetInput(Index);
		if (!CurrentInput)
		{
			break;
		}
		const FString InputName = ToExpression->GetInputName(Index).ToString();
		AvailableInputs.Add(InputName);
		if (TargetIndex == INDEX_NONE && (Wanted.IsEmpty() || InputName.Equals(Wanted, ESearchCase::IgnoreCase)))
		{
			TargetIndex = Index;
			TargetInput = CurrentInput;
			if (!Wanted.IsEmpty())
			{
				break;
			}
		}
	}

	if (AvailableInputs.Num() == 0)
	{
		return JsonError(TEXT("Target expression has no inputs: ") + ToExpression->GetName());
	}

	if (TargetIndex == INDEX_NONE)
	{
		return TEXT("{\"error\":\"Input not found: ") + JsonEscape(Wanted) + TEXT("\",\"available_inputs\":") + JsonStringArray(AvailableInputs) + TEXT("}");
	}

	FExpressionInput* Input = TargetInput;
	if (!Input)
	{
		return JsonError(TEXT("Input pointer is null"));
	}

	const FString InputName = ToExpression->GetInputName(TargetIndex).ToString();
	const bool bHadConnection = Input->Expression != nullptr;
	const FString FromExpressionName = Input->Expression ? Input->Expression->GetName() : FString();
	const FString FromExpressionPath = Input->Expression ? Input->Expression->GetPathName() : FString();

	Material->Modify();
	ToExpression->Modify();

	Input->Expression = nullptr;
	Input->OutputIndex = 0;
	Input->InputName = NAME_None;
	Input->Mask = 0;
	Input->MaskR = 0;
	Input->MaskG = 0;
	Input->MaskB = 0;
	Input->MaskA = 0;

	ToExpression->PostEditChange();
	Material->PostEditChange();
	Material->MarkPackageDirty();

	FString Json = TEXT("{\"status\":\"ok\",\"action\":\"disconnect\",\"to_node\":\"") + JsonEscape(ToExpression->GetName()) + TEXT("\"");
	Json += TEXT(",\"to_input\":\"") + JsonEscape(InputName) + TEXT("\"");
	Json += TEXT(",\"had_connection\":") + FString(bHadConnection ? TEXT("true") : TEXT("false"));
	Json += TEXT(",\"disconnected_from\":\"") + JsonEscape(FromExpressionName) + TEXT("\"");
	Json += TEXT(",\"disconnected_from_path\":\"") + JsonEscape(FromExpressionPath) + TEXT("\"}");
	return Json;
}

FString UCliAnythingBridgeLibrary::GetTextureSourceInfo(UTexture2D* Texture)
{
	if (!Texture)
	{
		return JsonError(TEXT("Texture is null"));
	}

	FTextureSource& Source = Texture->Source;
	const int64 SizeX = Source.GetSizeX();
	const int64 SizeY = Source.GetSizeY();
	const int32 NumSlices = Source.GetNumSlices();
	const int32 NumMips = Source.GetNumMips();
	const int32 NumLayers = Source.GetNumLayers();
	const int32 NumBlocks = Source.GetNumBlocks();
	const int64 SizeOnDisk = Source.GetSizeOnDisk();
	const ETextureSourceFormat Format = Source.GetFormat();
	const bool bValidFormat = Format > TSF_Invalid && Format < TSF_MAX;
#if ENGINE_MAJOR_VERSION >= 5
	const bool bHasPayload = Source.HasPayloadData();
	const FTextureSourceFormatInfo& FormatInfo = GTextureSourceFormats[bValidFormat ? Format : TSF_Invalid];
	const FString FormatName = bValidFormat ? FString(FormatInfo.Name) : FString(TEXT("TSF_Invalid"));
	const int32 BytesPerPixel = bValidFormat ? FormatInfo.BytesPerPixel : 0;
	const int32 NumComponents = bValidFormat ? FormatInfo.NumComponents : 0;
#else
	const bool bHasPayload = SizeOnDisk > 0;
	const FString FormatName = GetTextureSourceFormatName426(Format);
	const int32 BytesPerPixel = bValidFormat ? FTextureSource::GetBytesPerPixel(Format) : 0;
	const int32 NumComponents = GetTextureSourceNumComponents426(Format);
#endif

	FString Json = TEXT("{\"status\":\"ok\",\"asset\":\"") + JsonEscape(Texture->GetPathName()) + TEXT("\"");
	Json += FString::Printf(TEXT(",\"source_size\":{\"x\":%lld,\"y\":%lld,\"slices\":%d}"), SizeX, SizeY, NumSlices);
	Json += TEXT(",\"source_format\":\"") + JsonEscape(FormatName) + TEXT("\"");
	Json += FString::Printf(TEXT(",\"source_format_value\":%d"), static_cast<int32>(Format));
	Json += FString::Printf(TEXT(",\"num_mips\":%d,\"num_layers\":%d,\"num_blocks\":%d"), NumMips, NumLayers, NumBlocks);
	Json += FString::Printf(TEXT(",\"bytes_per_pixel\":%d,\"num_components\":%d,\"size_on_disk\":%lld"), BytesPerPixel, NumComponents, SizeOnDisk);
	Json += TEXT(",\"has_payload\":") + FString(bHasPayload ? TEXT("true") : TEXT("false"));

	const uint8* Data = nullptr;
	int64 MipSize = 0;
	if (bHasPayload && NumMips > 0 && SizeX > 0 && SizeY > 0)
	{
		MipSize = Source.CalcMipSize(0);
#if ENGINE_MAJOR_VERSION >= 5
		Data = Source.LockMipReadOnly(0);
#else
		Data = Source.LockMip(0);
#endif
	}
	Json += FString::Printf(TEXT(",\"mip0_bytes\":%lld"), MipSize);

	auto AppendByteStats = [&Json](const TCHAR* FieldName, const uint8* Bytes, int64 PixelCount, int32 Stride, int32 Offset, int32 FullValue)
	{
		if (!Bytes || PixelCount <= 0 || Stride <= 0)
		{
			Json += FString::Printf(TEXT(",\"%s\":{\"available\":false}"), FieldName);
			return;
		}
		int32 MinValue = 255;
		int32 MaxValue = 0;
		int64 ZeroCount = 0;
		int64 FullCount = 0;
		double Sum = 0.0;
		for (int64 Index = 0; Index < PixelCount; ++Index)
		{
			const int32 Value = Bytes[Index * Stride + Offset];
			MinValue = FMath::Min(MinValue, Value);
			MaxValue = FMath::Max(MaxValue, Value);
			ZeroCount += Value == 0 ? 1 : 0;
			FullCount += Value == FullValue ? 1 : 0;
			Sum += static_cast<double>(Value);
		}
		Json += FString::Printf(
			TEXT(",\"%s\":{\"available\":true,\"min\":%d,\"max\":%d,\"mean\":%.6f,\"zero_count\":%lld,\"full_count\":%lld,\"nonzero_count\":%lld,\"pixel_count\":%lld}"),
			FieldName, MinValue, MaxValue, Sum / static_cast<double>(PixelCount), ZeroCount, FullCount, PixelCount - ZeroCount, PixelCount);
	};

	const int64 PixelCount = SizeX * SizeY * FMath::Max<int32>(NumSlices, 1);
	if (Data && Format == TSF_BGRA8)
	{
		AppendByteStats(TEXT("alpha_stats"), Data, PixelCount, 4, 3, 255);
	}
	else
	{
		Json += TEXT(",\"alpha_stats\":{\"available\":false,\"reason\":\"alpha stats currently supported for TSF_BGRA8 source data\"}");
	}
	if (Data && Format == TSF_G8)
	{
		AppendByteStats(TEXT("value_stats"), Data, PixelCount, 1, 0, 255);
	}
	else
	{
		Json += TEXT(",\"value_stats\":{\"available\":false}");
	}

	if (Data)
	{
		Source.UnlockMip(0);
	}

	Json += TEXT("}");
	return Json;
}

FVector4 UCliAnythingBridgeLibrary::GetActiveViewportScreenBounds()
{
	FVector4 Bounds(0.0f, 0.0f, 0.0f, 0.0f);
	if (!FModuleManager::Get().IsModuleLoaded("LevelEditor")) return Bounds;
	FLevelEditorModule& LevelEditorModule = FModuleManager::GetModuleChecked<FLevelEditorModule>("LevelEditor");
	TSharedPtr<ILevelEditor> ActiveLevelEditor = LevelEditorModule.GetFirstLevelEditor();
	if (!ActiveLevelEditor.IsValid()) return Bounds;
	auto ActiveViewport = ActiveLevelEditor->GetActiveViewportInterface();
	if (!ActiveViewport.IsValid()) return Bounds;
	TSharedPtr<SViewport> ViewportWidget = ActiveViewport->GetViewportWidget().Pin();
	if (!ViewportWidget.IsValid()) return Bounds;
	FGeometry ViewportGeometry = ViewportWidget->GetCachedGeometry();
	FVector2D AbsolutePosition = ViewportGeometry.GetAbsolutePositionAtCoordinates(FVector2D(0.0f, 0.0f));
	FVector2D AbsoluteSize = ViewportGeometry.GetAbsoluteSize();
	Bounds.X = FMath::RoundToInt(AbsolutePosition.X);
	Bounds.Y = FMath::RoundToInt(AbsolutePosition.Y);
	Bounds.Z = FMath::RoundToInt(AbsoluteSize.X);
	Bounds.W = FMath::RoundToInt(AbsoluteSize.Y);
	return Bounds;
}

bool UCliAnythingBridgeLibrary::TakeActiveViewportScreenshot(const FString& OutputPath, bool bIncludeUI)
{
	if (OutputPath.IsEmpty() || !FModuleManager::Get().IsModuleLoaded("LevelEditor"))
	{
		return false;
	}

	FLevelEditorModule& LevelEditorModule = FModuleManager::GetModuleChecked<FLevelEditorModule>("LevelEditor");
	TSharedPtr<ILevelEditor> ActiveLevelEditor = LevelEditorModule.GetFirstLevelEditor();
	if (!ActiveLevelEditor.IsValid())
	{
		return false;
	}

	auto ActiveViewport = ActiveLevelEditor->GetActiveViewportInterface();
	if (!ActiveViewport.IsValid())
	{
		for (const auto& Viewport : ActiveLevelEditor->GetViewports())
		{
			if (Viewport.IsValid() && Viewport->GetSharedActiveViewport().IsValid())
			{
				ActiveViewport = Viewport;
				break;
			}
		}
		if (!ActiveViewport.IsValid())
		{
			return false;
		}
	}

	TSharedPtr<FSceneViewport> SceneViewport = ActiveViewport->GetSharedActiveViewport();
	if (!SceneViewport.IsValid())
	{
		return false;
	}

	SceneViewport->Draw();
	FlushRenderingCommands();

	FIntPoint Size;
	TArray<FColor> Pixels;
	if (bIncludeUI)
	{
		if (!FSlateApplication::IsInitialized())
		{
			return false;
		}
		TSharedPtr<SViewport> ViewportWidget = ActiveViewport->GetViewportWidget().Pin();
		if (!ViewportWidget.IsValid())
		{
			return false;
		}
		FIntVector ScreenshotSize;
		if (!FSlateApplication::Get().TakeScreenshot(ViewportWidget.ToSharedRef(), Pixels, ScreenshotSize))
		{
			return false;
		}
		Size = FIntPoint(ScreenshotSize.X, ScreenshotSize.Y);
	}
	else
	{
		Size = SceneViewport->GetRenderTargetTextureSizeXY();
		const FIntRect CaptureRect(0, 0, Size.X, Size.Y);
		Pixels.SetNum(CaptureRect.Area());
		if (!SceneViewport->ReadPixels(
			Pixels,
			FReadSurfaceDataFlags(RCM_UNorm, CubeFace_MAX),
			CaptureRect))
		{
			return false;
		}
	}
	if (Size.X <= 0 || Size.Y <= 0)
	{
		return false;
	}
	const int64 PixelCount = static_cast<int64>(Size.X) * Size.Y;
	if (Pixels.Num() != PixelCount)
	{
		return false;
	}
	for (int64 Index = 0; Index < PixelCount; ++Index)
	{
		Pixels[Index].A = 255;
	}

#if ENGINE_MAJOR_VERSION >= 5
	TArray64<uint8> CompressedPng;
	FImageUtils::PNGCompressImageArray(
		Size.X,
		Size.Y,
		TArrayView64<const FColor>(Pixels.GetData(), PixelCount),
		CompressedPng);
#else
	TArray<uint8> CompressedPng;
	FImageUtils::CompressImageArray(Size.X, Size.Y, Pixels, CompressedPng);
#endif
	if (CompressedPng.Num() == 0)
	{
		return false;
	}

	const FString Directory = FPaths::GetPath(OutputPath);
	if (!Directory.IsEmpty() && !IFileManager::Get().MakeDirectory(*Directory, true))
	{
		return false;
	}
	return FFileHelper::SaveArrayToFile(CompressedPng, *OutputPath);
}

extern TArray<FString> GCapturedEngineErrors;
extern FCriticalSection GCapturedEngineErrorsMutex;

TArray<FString> UCliAnythingBridgeLibrary::GetRecentEngineErrors(int32 Count)
{
	TArray<FString> Result;
	{
		FScopeLock Lock(&GCapturedEngineErrorsMutex);
		int32 NumLogs = GCapturedEngineErrors.Num();
		int32 StartIdx = FMath::Max(0, NumLogs - Count);
		for (int32 i = StartIdx; i < NumLogs; ++i) { Result.Add(GCapturedEngineErrors[i]); }
	}
	return Result;
}

FString UCliAnythingBridgeLibrary::GetPluginVersion()
{
	return TEXT("1.24");
}

static bool ResolveMaterialProperty(const FString& PropertyName, EMaterialProperty& OutProperty)
{
	FString Name = PropertyName;
	Name.TrimStartAndEndInline();
	if (Name.Equals(TEXT("BaseColor"), ESearchCase::IgnoreCase)) OutProperty = MP_BaseColor;
	else if (Name.Equals(TEXT("Metallic"), ESearchCase::IgnoreCase)) OutProperty = MP_Metallic;
	else if (Name.Equals(TEXT("Specular"), ESearchCase::IgnoreCase)) OutProperty = MP_Specular;
	else if (Name.Equals(TEXT("Roughness"), ESearchCase::IgnoreCase)) OutProperty = MP_Roughness;
	else if (Name.Equals(TEXT("Normal"), ESearchCase::IgnoreCase)) OutProperty = MP_Normal;
	else if (Name.Equals(TEXT("EmissiveColor"), ESearchCase::IgnoreCase)) OutProperty = MP_EmissiveColor;
	else if (Name.Equals(TEXT("Opacity"), ESearchCase::IgnoreCase)) OutProperty = MP_Opacity;
	else if (Name.Equals(TEXT("OpacityMask"), ESearchCase::IgnoreCase)) OutProperty = MP_OpacityMask;
	else if (Name.Equals(TEXT("WorldPositionOffset"), ESearchCase::IgnoreCase)) OutProperty = MP_WorldPositionOffset;
	else if (Name.Equals(TEXT("AmbientOcclusion"), ESearchCase::IgnoreCase)) OutProperty = MP_AmbientOcclusion;
	else if (Name.Equals(TEXT("SubsurfaceColor"), ESearchCase::IgnoreCase)) OutProperty = MP_SubsurfaceColor;
	else return false;
	return true;
}

FString UCliAnythingBridgeLibrary::ConnectMaterialOutput(UMaterialExpression* FromExpression, const FString& FromOutputName, const FString& PropertyName)
{
	if (!FromExpression)
	{
		return JsonError(TEXT("Source expression is null"));
	}

	EMaterialProperty Property = MP_MAX;
	if (!ResolveMaterialProperty(PropertyName, Property))
	{
		return JsonError(TEXT("Unknown material property: ") + PropertyName);
	}
	if (!UMaterialEditingLibrary::ConnectMaterialProperty(FromExpression, FromOutputName, Property))
	{
		return JsonError(TEXT("ConnectMaterialProperty returned false for: ") + PropertyName);
	}

	return TEXT("{\"status\":\"ok\",\"action\":\"connect\",\"to\":\"MaterialOutput.")
		+ JsonEscape(PropertyName)
		+ TEXT("\"}");
}

FString UCliAnythingBridgeLibrary::DisconnectMaterialOutput(UMaterial* Material, const FString& PropertyName)
{
	if (!Material)
	{
		return JsonError(TEXT("Material is null"));
	}

	EMaterialProperty Property = MP_MAX;
	if (!ResolveMaterialProperty(PropertyName, Property))
	{
		return JsonError(TEXT("Unknown material property: ") + PropertyName);
	}

	FExpressionInput* Input = Material->GetExpressionInputForProperty(Property);
	if (!Input)
	{
		return JsonError(TEXT("Material property input is unavailable: ") + PropertyName);
	}

	Material->Modify();
	Input->Expression = nullptr;
	Input->OutputIndex = 0;
	Material->PostEditChange();
	Material->MarkPackageDirty();

	return TEXT("{\"status\":\"ok\",\"action\":\"disconnect\",\"to\":\"MaterialOutput.")
		+ JsonEscape(PropertyName)
		+ TEXT("\"}");
}

FString UCliAnythingBridgeLibrary::GetConsoleVariableInfo(const FString& Name)
{
	IConsoleVariable* Var = IConsoleManager::Get().FindConsoleVariable(*Name);
	FString Json = TEXT("{\"name\":\"") + JsonEscape(Name) + TEXT("\"");
	if (!Var)
	{
		Json += TEXT(",\"exists\":false,\"value\":\"\"}");
		return Json;
	}

	Json += TEXT(",\"exists\":true");
	Json += TEXT(",\"value\":\"") + JsonEscape(Var->GetString()) + TEXT("\"");
	Json += FString::Printf(TEXT(",\"flags\":%d"), Var->GetFlags());
	Json += TEXT("}");
	return Json;
}

TArray<FString> UCliAnythingBridgeLibrary::GetMaterialHLSLCode(UMaterialInterface* Material, const FString& OutputPath)
{
	TArray<FString> Result;
	if (!Material || OutputPath.IsEmpty()) return Result;
	UMaterial* BaseMat = Material->GetMaterial();
	if (!BaseMat) return Result;
#if ENGINE_MAJOR_VERSION >= 5
	const EShaderPlatform Platform = GMaxRHIShaderPlatform;
	FMaterialResource* Resource = BaseMat->GetMaterialResource(Platform);
#else
	FMaterialResource* Resource = BaseMat->GetMaterialResource(GMaxRHIFeatureLevel);
#endif
	if (!Resource) return Result;
	FString Source;
	if (!Resource->GetMaterialExpressionSource(Source)) return Result;
	if (FFileHelper::SaveStringToFile(Source, *OutputPath, FFileHelper::EEncodingOptions::ForceUTF8WithoutBOM))
	{
		Result.Add(OutputPath);
	}
	return Result;
}

TArray<FString> UCliAnythingBridgeLibrary::GetMaterialShaderSource(UMaterialInterface* Material, const FString& OutputDir)
{
	TArray<FString> Result;
	if (!Material || OutputDir.IsEmpty()) return Result;
	UMaterial* BaseMat = Material->GetMaterial();
	if (!BaseMat) return Result;
	const EShaderPlatform Platform = GMaxRHIShaderPlatform;
	if (!GEngine || !GEngine->HandleRecompileShadersCommand(TEXT("Changed"), *GLog))
	{
		return Result;
	}

	FMaterialResourceExtractSource* ExtractResource = new FMaterialResourceExtractSource();
#if ENGINE_MAJOR_VERSION >= 5
	ExtractResource->SetMaterial(BaseMat, nullptr, Platform, EMaterialQualityLevel::High);
#else
	ExtractResource->SetMaterial(BaseMat, nullptr, GMaxRHIFeatureLevel, EMaterialQualityLevel::High);
#endif
	BaseMat->UpdateCachedExpressionData();
#if ENGINE_MAJOR_VERSION >= 5
	ExtractResource->CacheShaders(EMaterialShaderPrecompileMode::Default);
#else
	ExtractResource->CacheShaders(Platform);
#endif
	GShaderCompilingManager->FinishAllCompilation();

	const bool bFinished = ExtractResource->IsCompilationFinished();
	const FMaterialShaderMap* ShaderMap = ExtractResource->GetGameThreadShaderMap();
	if (bFinished && ShaderMap)
	{
		TMap<FShaderId, TShaderRef<FShader>> ShaderList;
		ShaderMap->GetShaderList(ShaderList);
		for (const auto& Pair : ShaderList)
		{
			const FShaderId& ShaderId = Pair.Key;
			const TShaderRef<FShader>& ShaderRef = Pair.Value;
#if ENGINE_MAJOR_VERSION >= 5
			const FMemoryImageString* Source = ShaderMap->GetShaderSource(
				ShaderRef.GetVertexFactoryType(), ShaderRef.GetType(), ShaderId.PermutationId);
#else
			const FMemoryImageString* Source = ShaderMap->GetShaderSource(ShaderRef.GetType()->GetFName());
#endif
			if (!Source || Source->Len() == 0) continue;

			FString ShaderName = ShaderRef.GetType()->GetName();
			if (ShaderRef.GetVertexFactoryType())
			{
				ShaderName += TEXT("_");
				ShaderName += ShaderRef.GetVertexFactoryType()->GetName();
			}
			if (ShaderId.PermutationId != 0)
			{
				ShaderName += FString::Printf(TEXT("_Perm%d"), ShaderId.PermutationId);
			}
			ShaderName.ReplaceCharInline(TEXT('<'), TEXT('_'));
			ShaderName.ReplaceCharInline(TEXT('>'), TEXT('_'));
			ShaderName.ReplaceCharInline(TEXT(':'), TEXT('_'));
			ShaderName.ReplaceCharInline(TEXT('"'), TEXT('_'));
			ShaderName.ReplaceCharInline(TEXT('/'), TEXT('_'));
			ShaderName.ReplaceCharInline(TEXT('\\'), TEXT('_'));
			ShaderName.ReplaceCharInline(TEXT('|'), TEXT('_'));
			ShaderName.ReplaceCharInline(TEXT('?'), TEXT('_'));
			ShaderName.ReplaceCharInline(TEXT('*'), TEXT('_'));

			FString FilePath = FPaths::Combine(OutputDir, ShaderName + TEXT(".usf"));
			IFileManager::Get().MakeDirectory(*OutputDir, true);
			if (FFileHelper::SaveStringToFile(FString(**Source), *FilePath, FFileHelper::EEncodingOptions::ForceUTF8WithoutBOM))
			{
				int32 LineCount = 0;
				for (int32 i = 0; i < Source->Len(); ++i) { if ((**Source)[i] == TEXT('\n')) LineCount++; }
				Result.Add(FString::Printf(TEXT("%s\t%s\t%d"), *ShaderName, *FilePath, LineCount));
			}
		}
	}

#if ENGINE_MAJOR_VERSION >= 5
	TArray<TRefCountPtr<FMaterial>> MaterialsToDelete;
	if (ExtractResource->PrepareDestroy_GameThread())
	{
		MaterialsToDelete.Add(ExtractResource);
		FMaterial::DeleteMaterialsOnRenderThread(MaterialsToDelete);
	}
	else
	{
		delete ExtractResource;
	}
#else
	delete ExtractResource;
#endif
	return Result;
}

// Escape a string for safe embedding in a JSON value ("..." context).
// UE's ReplaceCharWithEscapedChar() is designed for C++ string literals, not JSON,
// and produces invalid sequences like \\' from UE metadata tooltips.
static FString JsonEscape(const FString& Input)
{
	FString Result;
	Result.Reserve(Input.Len() + 16);
	for (const TCHAR Ch : Input)
	{
		switch (Ch)
		{
		case TEXT('"'):  Result += TEXT("\\\""); break;
		case TEXT('\\'): Result += TEXT("\\\\"); break;
		case TEXT('\n'): Result += TEXT("\\n");  break;
		case TEXT('\r'): Result += TEXT("\\r");  break;
		case TEXT('\t'): Result += TEXT("\\t");  break;
		default:        Result += Ch;            break;
		}
	}
	return Result;
}

static FString JsonError(const FString& Message)
{
	return TEXT("{\"error\":\"") + JsonEscape(Message) + TEXT("\"}");
}

static FString JsonStringArray(const TArray<FString>& Values)
{
	FString Result = TEXT("[");
	for (int32 Index = 0; Index < Values.Num(); ++Index)
	{
		if (Index > 0)
		{
			Result += TEXT(",");
		}
		Result += TEXT("\"") + JsonEscape(Values[Index]) + TEXT("\"");
	}
	Result += TEXT("]");
	return Result;
}

static UClass* FindWidgetClassByName(const FString& ClassName)
{
	FString Name = ClassName;
	Name.TrimStartAndEndInline();
	Name.RemoveFromStart(TEXT("unreal."));
	if (Name.IsEmpty()) return nullptr;

	if (Name.StartsWith(TEXT("/Script/")) || Name.Contains(TEXT(".")))
	{
		if (UClass* LoadedClass = LoadClass<UWidget>(nullptr, *Name))
		{
			return LoadedClass->IsChildOf(UWidget::StaticClass()) ? LoadedClass : nullptr;
		}
	}

	for (TObjectIterator<UClass> It; It; ++It)
	{
		UClass* Candidate = *It;
		if (!Candidate || !Candidate->IsChildOf(UWidget::StaticClass())) continue;
		if (Candidate->GetName() == Name || Candidate->GetPathName() == Name)
		{
			return Candidate;
		}
	}
	return nullptr;
}

static FString WidgetJson(UWidget* Widget, UWidgetBlueprint* Blueprint)
{
	if (!Widget) return TEXT("{}");

	FString Json = TEXT("{\"name\":\"") + JsonEscape(Widget->GetName()) + TEXT("\"");
	Json += TEXT(",\"class\":\"") + JsonEscape(Widget->GetClass()->GetName()) + TEXT("\"");
	Json += TEXT(",\"path\":\"") + JsonEscape(Widget->GetPathName()) + TEXT("\"");
	Json += TEXT(",\"is_variable\":");
	Json += Widget->bIsVariable ? TEXT("true") : TEXT("false");

	const bool bIsRoot = Blueprint && Blueprint->WidgetTree && Blueprint->WidgetTree->RootWidget == Widget;
	Json += TEXT(",\"is_root\":");
	Json += bIsRoot ? TEXT("true") : TEXT("false");

	int32 ChildIndex = INDEX_NONE;
	if (UPanelWidget* Parent = UWidgetTree::FindWidgetParent(Widget, ChildIndex))
	{
		Json += TEXT(",\"parent\":\"") + JsonEscape(Parent->GetName()) + TEXT("\"");
		Json += FString::Printf(TEXT(",\"child_index\":%d"), ChildIndex);
	}

	if (UCanvasPanelSlot* CanvasSlot = Cast<UCanvasPanelSlot>(Widget->Slot))
	{
		const FVector2D Position = CanvasSlot->GetPosition();
		const FVector2D Size = CanvasSlot->GetSize();
		Json += FString::Printf(
			TEXT(",\"slot\":{\"type\":\"CanvasPanelSlot\",\"position\":[%.6g,%.6g],\"size\":[%.6g,%.6g],\"z_order\":%d}"),
			Position.X, Position.Y, Size.X, Size.Y, CanvasSlot->GetZOrder());
	}

	if (UTextBlock* TextBlock = Cast<UTextBlock>(Widget))
	{
		Json += TEXT(",\"text\":\"") + JsonEscape(TextBlock->GetText().ToString()) + TEXT("\"");
	}

	if (UImage* Image = Cast<UImage>(Widget))
	{
#if ENGINE_MAJOR_VERSION >= 5
		const FSlateBrush& Brush = Image->GetBrush();
#else
		const FSlateBrush& Brush = Image->Brush;
#endif
		UObject* Resource = Brush.GetResourceObject();
		const FVector2D BrushSize = Brush.GetImageSize();
		Json += TEXT(",\"brush\":{");
		Json += TEXT("\"resource\":");
		if (Resource)
		{
			Json += TEXT("\"") + JsonEscape(Resource->GetPathName()) + TEXT("\"");
			Json += TEXT(",\"resource_class\":\"") + JsonEscape(Resource->GetClass()->GetName()) + TEXT("\"");
		}
		else
		{
			Json += TEXT("null");
		}
		Json += FString::Printf(TEXT(",\"image_size\":[%.6g,%.6g]"), BrushSize.X, BrushSize.Y);
		Json += FString::Printf(TEXT(",\"draw_as\":%d"), static_cast<int32>(Brush.GetDrawType()));
		Json += TEXT("}");
	}

	if (UPanelWidget* Panel = Cast<UPanelWidget>(Widget))
	{
		Json += TEXT(",\"children\":[");
		for (int32 Index = 0; Index < Panel->GetChildrenCount(); ++Index)
		{
			if (Index > 0) Json += TEXT(",");
			if (UWidget* Child = Panel->GetChildAt(Index))
			{
				Json += TEXT("{\"name\":\"") + JsonEscape(Child->GetName()) + TEXT("\"");
				Json += TEXT(",\"class\":\"") + JsonEscape(Child->GetClass()->GetName()) + TEXT("\"}");
			}
			else
			{
				Json += TEXT("{}");
			}
		}
		Json += TEXT("]");
	}

	Json += TEXT("}");
	return Json;
}

FString UCliAnythingBridgeLibrary::SetWidgetBlueprintRoot(UWidgetBlueprint* Blueprint, const FString& RootWidgetClassName, const FString& RootWidgetName, bool bIsVariable)
{
	if (!Blueprint) return JsonError(TEXT("WidgetBlueprint is null."));
	if (!Blueprint->WidgetTree) return JsonError(TEXT("WidgetBlueprint has no WidgetTree."));

	UClass* RootClass = FindWidgetClassByName(RootWidgetClassName.IsEmpty() ? TEXT("CanvasPanel") : RootWidgetClassName);
	if (!RootClass) return JsonError(TEXT("Root widget class not found or not a UWidget: ") + RootWidgetClassName);

	const FName RootName = RootWidgetName.IsEmpty() ? FName(TEXT("RootCanvas")) : FName(*RootWidgetName);
	UWidget* Root = Blueprint->WidgetTree->RootWidget;
	if (Root)
	{
		if (Root->GetClass() != RootClass)
		{
			return JsonError(
				TEXT("WidgetBlueprint already has a root widget of class ")
				+ Root->GetClass()->GetName()
				+ TEXT("; requested ")
				+ RootClass->GetName()
			);
		}

		UWidget* NameOwner = Blueprint->WidgetTree->FindWidget(RootName);
		if (NameOwner && NameOwner != Root)
		{
			return JsonError(TEXT("Widget name already exists: ") + RootName.ToString());
		}

		Root->Modify();
		if (Root->GetFName() != RootName && !Root->Rename(*RootName.ToString(), Blueprint->WidgetTree))
		{
			return JsonError(TEXT("Failed to rename existing root widget to: ") + RootName.ToString());
		}
		Root->bIsVariable = bIsVariable;
		FBlueprintEditorUtils::MarkBlueprintAsStructurallyModified(Blueprint);
		Blueprint->MarkPackageDirty();

		FString ExistingJson = TEXT("{\"status\":\"ok\",\"action\":\"set_root\",\"root\":");
		ExistingJson += WidgetJson(Root, Blueprint);
		ExistingJson += TEXT("}");
		return ExistingJson;
	}

	if (Blueprint->WidgetTree->FindWidget(RootName))
	{
		return JsonError(TEXT("Widget name already exists: ") + RootName.ToString());
	}

	Root = Blueprint->WidgetTree->ConstructWidget<UWidget>(RootClass, RootName);
	if (!Root) return JsonError(TEXT("Failed to construct root widget."));

	Root->bIsVariable = bIsVariable;
	Blueprint->WidgetTree->RootWidget = Root;
	if (bIsVariable)
	{
#if ENGINE_MAJOR_VERSION >= 5
		Blueprint->OnVariableAdded(Root->GetFName());
#endif
	}
	FBlueprintEditorUtils::MarkBlueprintAsStructurallyModified(Blueprint);
	Blueprint->MarkPackageDirty();

	FString Json = TEXT("{\"status\":\"ok\",\"action\":\"set_root\",\"root\":");
	Json += WidgetJson(Root, Blueprint);
	Json += TEXT("}");
	return Json;
}

FString UCliAnythingBridgeLibrary::AddWidgetToCanvas(UWidgetBlueprint* Blueprint, const FString& WidgetClassName, const FString& WidgetName, const FString& ParentWidgetName, bool bIsVariable, float X, float Y, float Width, float Height, int32 ZOrder, const FString& Text)
{
	if (!Blueprint) return JsonError(TEXT("WidgetBlueprint is null."));
	if (!Blueprint->WidgetTree) return JsonError(TEXT("WidgetBlueprint has no WidgetTree."));
	if (!Blueprint->WidgetTree->RootWidget) return JsonError(TEXT("WidgetBlueprint has no root widget."));

	UClass* WidgetClass = FindWidgetClassByName(WidgetClassName);
	if (!WidgetClass) return JsonError(TEXT("Widget class not found or not a UWidget: ") + WidgetClassName);
	if (WidgetName.IsEmpty()) return JsonError(TEXT("Widget name is required."));

	const FName NewWidgetName(*WidgetName);
	if (Blueprint->WidgetTree->FindWidget(NewWidgetName))
	{
		return JsonError(TEXT("Widget name already exists: ") + WidgetName);
	}

	UWidget* ParentWidget = nullptr;
	if (ParentWidgetName.IsEmpty())
	{
		ParentWidget = Blueprint->WidgetTree->RootWidget;
	}
	else
	{
		ParentWidget = Blueprint->WidgetTree->FindWidget(FName(*ParentWidgetName));
	}

	UCanvasPanel* Canvas = Cast<UCanvasPanel>(ParentWidget);
	if (!Canvas)
	{
		const FString ParentLabel = ParentWidget ? ParentWidget->GetName() : ParentWidgetName;
		return JsonError(TEXT("Parent widget is not a CanvasPanel: ") + ParentLabel);
	}

	UWidget* Child = Blueprint->WidgetTree->ConstructWidget<UWidget>(WidgetClass, NewWidgetName);
	if (!Child) return JsonError(TEXT("Failed to construct widget: ") + WidgetName);

	Child->bIsVariable = bIsVariable;
	if (UTextBlock* TextBlock = Cast<UTextBlock>(Child))
	{
		if (!Text.IsEmpty())
		{
			TextBlock->SetText(FText::FromString(Text));
		}
	}

	UCanvasPanelSlot* Slot = Canvas->AddChildToCanvas(Child);
	if (!Slot) return JsonError(TEXT("Failed to add widget to CanvasPanel."));
	Slot->SetPosition(FVector2D(X, Y));
	if (Width >= 0.0f && Height >= 0.0f)
	{
		Slot->SetSize(FVector2D(Width, Height));
	}
	Slot->SetZOrder(ZOrder);

	if (bIsVariable)
	{
#if ENGINE_MAJOR_VERSION >= 5
		Blueprint->OnVariableAdded(Child->GetFName());
#endif
	}
	FBlueprintEditorUtils::MarkBlueprintAsStructurallyModified(Blueprint);
	Blueprint->MarkPackageDirty();

	FString Json = TEXT("{\"status\":\"ok\",\"action\":\"add_widget\",\"parent\":\"");
	Json += JsonEscape(Canvas->GetName());
	Json += TEXT("\",\"widget\":");
	Json += WidgetJson(Child, Blueprint);
	Json += TEXT("}");
	return Json;
}

FString UCliAnythingBridgeLibrary::SetWidgetImageProperties(UWidgetBlueprint* Blueprint, const FString& WidgetName, UObject* ResourceObject, bool bSetResource, bool bSetPosition, float X, float Y, bool bSetSize, float Width, float Height, bool bSetZOrder, int32 ZOrder, bool bSetBrushImageSize, float ImageWidth, float ImageHeight)
{
	if (!Blueprint) return JsonError(TEXT("WidgetBlueprint is null."));
	if (!Blueprint->WidgetTree) return JsonError(TEXT("WidgetBlueprint has no WidgetTree."));
	if (WidgetName.IsEmpty()) return JsonError(TEXT("Widget name is required."));

	UWidget* Widget = Blueprint->WidgetTree->FindWidget(FName(*WidgetName));
	if (!Widget) return JsonError(TEXT("Widget not found: ") + WidgetName);

	UImage* Image = Cast<UImage>(Widget);
	if (!Image) return JsonError(TEXT("Widget is not an Image: ") + WidgetName);

	Image->Modify();
	if (bSetResource)
	{
		if (!ResourceObject) return JsonError(TEXT("Brush resource is null."));
		Image->SetBrushResourceObject(ResourceObject);
	}

	if (bSetBrushImageSize)
	{
		if (ImageWidth < 0.0f || ImageHeight < 0.0f)
		{
			return JsonError(TEXT("Brush ImageSize must be non-negative."));
		}
#if ENGINE_MAJOR_VERSION >= 5
		FSlateBrush Brush = Image->GetBrush();
#else
		FSlateBrush Brush = Image->Brush;
#endif
		Brush.ImageSize = FVector2D(ImageWidth, ImageHeight);
		Image->SetBrush(Brush);
	}

	if (bSetPosition || bSetSize || bSetZOrder)
	{
		UCanvasPanelSlot* CanvasSlot = Cast<UCanvasPanelSlot>(Image->Slot);
		if (!CanvasSlot) return JsonError(TEXT("Image widget is not in a CanvasPanelSlot: ") + WidgetName);
		CanvasSlot->Modify();
		if (bSetPosition)
		{
			CanvasSlot->SetPosition(FVector2D(X, Y));
		}
		if (bSetSize)
		{
			CanvasSlot->SetSize(FVector2D(Width, Height));
		}
		if (bSetZOrder)
		{
			CanvasSlot->SetZOrder(ZOrder);
		}
	}

	FBlueprintEditorUtils::MarkBlueprintAsModified(Blueprint);
	Blueprint->MarkPackageDirty();

	FString Json = TEXT("{\"status\":\"ok\",\"action\":\"set_image\",\"widget\":");
	Json += WidgetJson(Image, Blueprint);
	Json += TEXT("}");
	return Json;
}

FString UCliAnythingBridgeLibrary::GetWidgetBlueprintTree(UWidgetBlueprint* Blueprint)
{
	if (!Blueprint) return JsonError(TEXT("WidgetBlueprint is null."));
	if (!Blueprint->WidgetTree) return JsonError(TEXT("WidgetBlueprint has no WidgetTree."));

	FString Json = TEXT("{\"status\":\"ok\",\"widget\":\"") + JsonEscape(Blueprint->GetPathName()) + TEXT("\"");
	if (Blueprint->WidgetTree->RootWidget)
	{
		Json += TEXT(",\"root\":");
		Json += WidgetJson(Blueprint->WidgetTree->RootWidget, Blueprint);
	}
	else
	{
		Json += TEXT(",\"root\":null");
	}

	TArray<UWidget*> Widgets;
	Blueprint->WidgetTree->GetAllWidgets(Widgets);
	Json += TEXT(",\"widgets\":[");
	for (int32 Index = 0; Index < Widgets.Num(); ++Index)
	{
		if (Index > 0) Json += TEXT(",");
		Json += WidgetJson(Widgets[Index], Blueprint);
	}
	Json += TEXT("]}");
	return Json;
}

FString UCliAnythingBridgeLibrary::GetClassInfo(const FString& ClassName, bool bIncludeInherited)
{
	// Find the UClass by name
	UClass* FoundClass = nullptr;
	for (TObjectIterator<UClass> It; It; ++It)
	{
		if (It->GetName() == ClassName)
		{
			FoundClass = *It;
			break;
		}
	}

	if (!FoundClass) return TEXT("{}");

	// Build JSON using TFieldIterator (same system the Details panel uses)
	FString Json = TEXT("{");
	Json += TEXT("\"class\":\"") + JsonEscape(FoundClass->GetName()) + TEXT("\"");

	// --- Properties: only those with EditAnywhere/VisibleAnywhere (like Details panel) ---
	Json += TEXT(",\"properties\":[");
	bool bFirst = true;

	EFieldIteratorFlags::SuperClassFlags SuperFlag = bIncludeInherited
		? EFieldIteratorFlags::IncludeSuper : EFieldIteratorFlags::ExcludeSuper;

	for (TFieldIterator<FProperty> It(FoundClass, SuperFlag, EFieldIteratorFlags::IncludeDeprecated); It; ++It)
	{
		const FProperty* Prop = *It;
		if (!Prop) continue;

		// Expose all reflected properties (no filter) — some types like
		// FExpressionInput have bare UPROPERTY() without Edit/Visible flags
		// but are still essential for understanding material expression inputs.
		const EPropertyFlags Flags = Prop->PropertyFlags;

		if (!bFirst) Json += TEXT(",");
		bFirst = false;

		Json += TEXT("{\"name\":\"") + JsonEscape(Prop->GetName()) + TEXT("\"");
		Json += TEXT(",\"type\":\"") + JsonEscape(Prop->GetCPPType()) + TEXT("\"");
		Json += TEXT(",\"owner\":\"") + JsonEscape(Prop->GetOwnerClass()->GetName()) + TEXT("\"");

		FString Category = Prop->GetMetaData(TEXT("Category"));
		if (!Category.IsEmpty())
			Json += TEXT(",\"category\":\"") + JsonEscape(Category) + TEXT("\"");

		FString Tooltip = Prop->GetMetaData(TEXT("Tooltip"));
		if (!Tooltip.IsEmpty())
		{
			Tooltip.ReplaceInline(TEXT("\r\n"), TEXT(" "));
			Tooltip.ReplaceInline(TEXT("\n"), TEXT(" "));
			Json += TEXT(",\"tooltip\":\"") + JsonEscape(Tooltip) + TEXT("\"");
		}

		Json += TEXT(",\"read\":");
		Json += (Flags & CPF_BlueprintVisible) ? TEXT("true") : TEXT("false");
		Json += TEXT(",\"write\":");
		Json += (Flags & CPF_Edit) ? TEXT("true") : TEXT("false");

		Json += TEXT("}");
	}
	Json += TEXT("]");

	// --- Functions: UFUNCTION only, skip internal/deprecated ---
	Json += TEXT(",\"functions\":[");
	bFirst = true;

	for (TFieldIterator<UFunction> It(FoundClass, SuperFlag, EFieldIteratorFlags::IncludeDeprecated); It; ++It)
	{
		const UFunction* Func = *It;
		if (!Func) continue;
		// Skip deprecated and Blueprint-internal functions
		if (Func->HasMetaData(TEXT("DeprecatedFunction")) ||
			Func->HasMetaData(TEXT("BlueprintInternalUseOnly"))) continue;

		if (!bFirst) Json += TEXT(",");
		bFirst = false;

		Json += TEXT("{\"name\":\"") + JsonEscape(Func->GetName()) + TEXT("\"");
		Json += TEXT(",\"owner\":\"") + JsonEscape(Func->GetOwnerClass()->GetName()) + TEXT("\"");

		FString FuncTooltip = Func->GetMetaData(TEXT("Tooltip"));
		if (!FuncTooltip.IsEmpty())
		{
			FuncTooltip.ReplaceInline(TEXT("\r\n"), TEXT(" "));
			FuncTooltip.ReplaceInline(TEXT("\n"), TEXT(" "));
			Json += TEXT(",\"tooltip\":\"") + JsonEscape(FuncTooltip) + TEXT("\"");
		}

		FProperty* ReturnProp = Func->GetReturnProperty();
		if (ReturnProp)
			Json += TEXT(",\"return_type\":\"") + JsonEscape(ReturnProp->GetCPPType()) + TEXT("\"");

		Json += TEXT(",\"params\":[");
		bool bFirstParam = true;
		for (TFieldIterator<FProperty> ParamIt(Func); ParamIt; ++ParamIt)
		{
			const FProperty* Param = *ParamIt;
			if (Param == ReturnProp) continue;
			if (Param->PropertyFlags & CPF_OutParm && !(Param->PropertyFlags & CPF_ConstParm)) continue;

			if (!bFirstParam) Json += TEXT(",");
			bFirstParam = false;
			Json += TEXT("{\"name\":\"") + JsonEscape(Param->GetName()) + TEXT("\"");
			Json += TEXT(",\"type\":\"") + JsonEscape(Param->GetCPPType()) + TEXT("\"");
			Json += TEXT("}");
		}
		Json += TEXT("]");

		Json += TEXT("}");
	}
	Json += TEXT("]");

	Json += TEXT("}");
	return Json;
}

FString UCliAnythingBridgeLibrary::GetStructInfo(UScriptStruct* Struct, bool bIncludeInherited)
{
	if (!Struct) return TEXT("{}");

	EFieldIteratorFlags::SuperClassFlags SuperFlag = bIncludeInherited
		? EFieldIteratorFlags::IncludeSuper : EFieldIteratorFlags::ExcludeSuper;

	FString Json = TEXT("{");
	Json += TEXT("\"struct\":\"") + JsonEscape(Struct->GetName()) + TEXT("\"");
	Json += TEXT(",\"struct_path\":\"") + JsonEscape(Struct->GetPathName()) + TEXT("\"");
	Json += TEXT(",\"properties\":[");

	bool bFirst = true;
	for (TFieldIterator<FProperty> It(Struct, SuperFlag, EFieldIteratorFlags::IncludeDeprecated); It; ++It)
	{
		const FProperty* Prop = *It;
		if (!Prop) continue;

		if (!bFirst) Json += TEXT(",");
		bFirst = false;

		Json += TEXT("{\"name\":\"") + JsonEscape(Prop->GetName()) + TEXT("\"");
		Json += TEXT(",\"type\":\"") + JsonEscape(Prop->GetCPPType()) + TEXT("\"");
		if (const UStruct* OwnerStruct = Prop->GetOwnerStruct())
		{
			Json += TEXT(",\"owner\":\"") + JsonEscape(OwnerStruct->GetName()) + TEXT("\"");
		}

		FString Category = Prop->GetMetaData(TEXT("Category"));
		if (!Category.IsEmpty())
		{
			Json += TEXT(",\"category\":\"") + JsonEscape(Category) + TEXT("\"");
		}

		FString Tooltip = Prop->GetMetaData(TEXT("Tooltip"));
		if (!Tooltip.IsEmpty())
		{
			Tooltip.ReplaceInline(TEXT("\r\n"), TEXT(" "));
			Tooltip.ReplaceInline(TEXT("\n"), TEXT(" "));
			Json += TEXT(",\"tooltip\":\"") + JsonEscape(Tooltip) + TEXT("\"");
		}

		const EPropertyFlags Flags = Prop->PropertyFlags;
		Json += TEXT(",\"read\":");
		Json += (Flags & CPF_BlueprintVisible) ? TEXT("true") : TEXT("false");
		Json += TEXT(",\"write\":");
		Json += (Flags & CPF_Edit) ? TEXT("true") : TEXT("false");
		Json += TEXT("}");
	}

	Json += TEXT("],\"functions\":[]}");
	return Json;
}

FString UCliAnythingBridgeLibrary::GetActorComponentTree(AActor* Actor, bool bIncludeVisualization)
{
	if (!Actor) return TEXT("[]");

	TArray<UActorComponent*> Components;
	Actor->GetComponents(Components);

	USceneComponent* RootComp = Actor->GetRootComponent();

	FString Json = TEXT("[");
	bool bFirst = true;
	for (UActorComponent* Comp : Components)
	{
		if (!Comp) continue;

		// Match the SCS Components tree in the Details panel: skip editor-only
		// visualization components (arrow gizmos, billboard icons, debug text, ...).
		if (!bIncludeVisualization && Comp->IsVisualizationComponent()) continue;

		if (!bFirst) Json += TEXT(",");
		bFirst = false;

		// Attach parent (scene components only); empty string for non-scene components
		FString ParentName;
		if (USceneComponent* SceneComp = Cast<USceneComponent>(Comp))
		{
			if (USceneComponent* Parent = SceneComp->GetAttachParent())
			{
				ParentName = Parent->GetName();
			}
		}

		const bool bIsRoot   = (Comp == RootComp);
		// RF_DefaultSubObject is set for components created via CreateDefaultSubobject
		// in the C++ constructor — i.e., "native" components. BP-added and instance
		// components lack this flag.
		const bool bIsNative = Comp->HasAnyFlags(RF_DefaultSubObject);

		Json += TEXT("{\"name\":\"") + JsonEscape(Comp->GetName()) + TEXT("\"");
		Json += TEXT(",\"class\":\"") + JsonEscape(Comp->GetClass()->GetName()) + TEXT("\"");
		Json += TEXT(",\"path\":\"") + JsonEscape(Comp->GetPathName()) + TEXT("\"");
		Json += TEXT(",\"is_root\":");
		Json += bIsRoot ? TEXT("true") : TEXT("false");
		Json += TEXT(",\"is_native\":");
		Json += bIsNative ? TEXT("true") : TEXT("false");
		if (!ParentName.IsEmpty())
		{
			Json += TEXT(",\"parent\":\"") + JsonEscape(ParentName) + TEXT("\"");
		}
		Json += TEXT("}");
	}
	Json += TEXT("]");
	return Json;
}
