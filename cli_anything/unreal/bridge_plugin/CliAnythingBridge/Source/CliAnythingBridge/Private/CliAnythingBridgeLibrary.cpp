#include "CliAnythingBridgeLibrary.h"

#include "Materials/Material.h"
#include "Materials/MaterialInterface.h"
#include "MaterialShared.h"
#include "RHIShaderPlatform.h"
#include "ShaderCompiler.h"
#include "ShaderCompilerCore.h"

#include "LevelEditor.h"
#include "SLevelViewport.h"
#include "Modules/ModuleManager.h"
#include "Framework/Application/SlateApplication.h"
#include "HAL/CriticalSection.h"
#include "Misc/FileHelper.h"
#include "Misc/Paths.h"

#include "UObject/UnrealType.h"
#include "UObject/UObjectIterator.h"
#include "UObject/TextProperty.h"

class FMaterialResourceExtractSource : public FMaterialResource
{
public:
	virtual void SetupExtraCompilationSettings(FExtraShaderCompilerSettings& Settings) const override
	{
		Settings.bExtractShaderSource = true;
	}
};

TArray<FString> UCliAnythingBridgeLibrary::GetMaterialCompileErrors(UMaterialInterface* Material)
{
	TArray<FString> Result;
	if (!Material) return Result;
	UMaterial* BaseMat = Material->GetMaterial();
	if (!BaseMat) return Result;
	const EShaderPlatform Platform = GMaxRHIShaderPlatform;
	for (int32 QualityLevel = 0; QualityLevel < EMaterialQualityLevel::Num; ++QualityLevel)
	{
		const FMaterialResource* Resource = BaseMat->GetMaterialResource(Platform, static_cast<EMaterialQualityLevel::Type>(QualityLevel));
		if (!Resource) continue;
		for (const FString& Error : Resource->GetCompileErrors()) { Result.AddUnique(Error); }
	}
	return Result;
}

FIntVector4 UCliAnythingBridgeLibrary::GetActiveViewportScreenBounds()
{
	FIntVector4 Bounds(0, 0, 0, 0);
	if (!FModuleManager::Get().IsModuleLoaded("LevelEditor")) return Bounds;
	FLevelEditorModule& LevelEditorModule = FModuleManager::GetModuleChecked<FLevelEditorModule>("LevelEditor");
	TSharedPtr<ILevelEditor> ActiveLevelEditor = LevelEditorModule.GetFirstLevelEditor();
	if (!ActiveLevelEditor.IsValid()) return Bounds;
	TSharedPtr<SLevelViewport> ActiveViewport = ActiveLevelEditor->GetActiveViewportInterface();
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
	return TEXT("1.8");
}

TArray<FString> UCliAnythingBridgeLibrary::GetMaterialHLSLCode(UMaterialInterface* Material, const FString& OutputPath)
{
	TArray<FString> Result;
	if (!Material || OutputPath.IsEmpty()) return Result;
	UMaterial* BaseMat = Material->GetMaterial();
	if (!BaseMat) return Result;
	const EShaderPlatform Platform = GMaxRHIShaderPlatform;
	FMaterialResource* Resource = BaseMat->GetMaterialResource(Platform);
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

	FMaterialResourceExtractSource* ExtractResource = new FMaterialResourceExtractSource();
	ExtractResource->SetMaterial(BaseMat, nullptr, Platform, EMaterialQualityLevel::High);
	BaseMat->UpdateCachedExpressionData();
	ExtractResource->CacheShaders(EMaterialShaderPrecompileMode::Default);
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
			const FMemoryImageString* Source = ShaderMap->GetShaderSource(
				ShaderRef.GetVertexFactoryType(), ShaderRef.GetType(), ShaderId.PermutationId);
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

		// Only show properties visible in Details panel
		const EPropertyFlags Flags = Prop->PropertyFlags;
		const bool bEditable = (Flags & CPF_Edit) != 0 || (Flags & CPF_EditConst) != 0;
		if (!bEditable) continue;

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
