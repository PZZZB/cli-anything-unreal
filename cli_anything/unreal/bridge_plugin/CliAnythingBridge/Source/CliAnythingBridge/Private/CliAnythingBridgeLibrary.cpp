#include "CliAnythingBridgeLibrary.h"

#include "Materials/Material.h"
#include "Materials/MaterialExpression.h"
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
#include "HAL/IConsoleManager.h"
#include "Misc/FileHelper.h"
#include "Misc/Paths.h"

#include "GameFramework/Actor.h"
#include "Components/ActorComponent.h"
#include "Components/SceneComponent.h"
#include "Blueprint/WidgetTree.h"
#include "Components/CanvasPanel.h"
#include "Components/CanvasPanelSlot.h"
#include "Components/PanelWidget.h"
#include "Components/TextBlock.h"
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
	return TEXT("1.15");
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
	if (Blueprint->WidgetTree->RootWidget) return JsonError(TEXT("WidgetBlueprint already has a root widget."));

	UClass* RootClass = FindWidgetClassByName(RootWidgetClassName.IsEmpty() ? TEXT("CanvasPanel") : RootWidgetClassName);
	if (!RootClass) return JsonError(TEXT("Root widget class not found or not a UWidget: ") + RootWidgetClassName);

	const FName RootName = RootWidgetName.IsEmpty() ? FName(TEXT("RootCanvas")) : FName(*RootWidgetName);
	if (Blueprint->WidgetTree->FindWidget(RootName))
	{
		return JsonError(TEXT("Widget name already exists: ") + RootName.ToString());
	}

	UWidget* Root = Blueprint->WidgetTree->ConstructWidget<UWidget>(RootClass, RootName);
	if (!Root) return JsonError(TEXT("Failed to construct root widget."));

	Root->bIsVariable = bIsVariable;
	Blueprint->WidgetTree->RootWidget = Root;
	if (bIsVariable)
	{
		Blueprint->OnVariableAdded(Root->GetFName());
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
		Blueprint->OnVariableAdded(Child->GetFName());
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
