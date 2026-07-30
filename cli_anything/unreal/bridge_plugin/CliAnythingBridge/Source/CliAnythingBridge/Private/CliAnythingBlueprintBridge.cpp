#include "CliAnythingBridgeLibrary.h"

#include "EdGraph/EdGraph.h"
#include "EdGraph/EdGraphNode.h"
#include "EdGraphSchema_K2.h"
#include "Engine/Blueprint.h"
#include "Kismet2/BlueprintEditorUtils.h"
#include "Kismet2/KismetEditorUtilities.h"

static FString BlueprintJsonEscape(const FString& Input)
{
	FString Result = Input;
	Result.ReplaceInline(TEXT("\\"), TEXT("\\\\"));
	Result.ReplaceInline(TEXT("\""), TEXT("\\\""));
	Result.ReplaceInline(TEXT("\r"), TEXT("\\r"));
	Result.ReplaceInline(TEXT("\n"), TEXT("\\n"));
	Result.ReplaceInline(TEXT("\t"), TEXT("\\t"));
	return Result;
}

static FString BlueprintJsonError(const FString& Message)
{
	return TEXT("{\"error\":\"") + BlueprintJsonEscape(Message) + TEXT("\"}");
}

static UEdGraph* FindBlueprintGraph(UBlueprint* Blueprint, const FString& GraphName)
{
	if (!Blueprint)
	{
		return nullptr;
	}

	TArray<UEdGraph*> Graphs;
	Blueprint->GetAllGraphs(Graphs);
	for (UEdGraph* Graph : Graphs)
	{
		if (Graph && Graph->GetName().Equals(GraphName, ESearchCase::CaseSensitive))
		{
			return Graph;
		}
	}
	return nullptr;
}

static bool MakeBlueprintPinType(const FString& TypeName, FEdGraphPinType& OutType)
{
	FString Normalized = TypeName;
	Normalized.TrimStartAndEndInline();
	Normalized.ToLowerInline();

	if (Normalized == TEXT("bool"))
	{
		OutType.PinCategory = UEdGraphSchema_K2::PC_Boolean;
	}
	else if (Normalized == TEXT("int") || Normalized == TEXT("integer"))
	{
		OutType.PinCategory = UEdGraphSchema_K2::PC_Int;
	}
	else if (Normalized == TEXT("float"))
	{
		OutType.PinCategory = UEdGraphSchema_K2::PC_Float;
	}
	else if (Normalized == TEXT("string"))
	{
		OutType.PinCategory = UEdGraphSchema_K2::PC_String;
	}
	else if (Normalized == TEXT("text"))
	{
		OutType.PinCategory = UEdGraphSchema_K2::PC_Text;
	}
	else if (Normalized == TEXT("name"))
	{
		OutType.PinCategory = UEdGraphSchema_K2::PC_Name;
	}
	else if (Normalized == TEXT("vector"))
	{
		OutType.PinCategory = UEdGraphSchema_K2::PC_Struct;
		OutType.PinSubCategoryObject = TBaseStructure<FVector>::Get();
	}
	else if (Normalized == TEXT("rotator"))
	{
		OutType.PinCategory = UEdGraphSchema_K2::PC_Struct;
		OutType.PinSubCategoryObject = TBaseStructure<FRotator>::Get();
	}
	else if (Normalized == TEXT("transform"))
	{
		OutType.PinCategory = UEdGraphSchema_K2::PC_Struct;
		OutType.PinSubCategoryObject = TBaseStructure<FTransform>::Get();
	}
	else
	{
		return false;
	}
	return true;
}

FString UCliAnythingBridgeLibrary::GetBlueprintInfo(UBlueprint* Blueprint)
{
	if (!Blueprint)
	{
		return BlueprintJsonError(TEXT("Blueprint is null."));
	}

	TArray<UEdGraph*> Graphs;
	Blueprint->GetAllGraphs(Graphs);
	UEdGraph* EventGraph = FBlueprintEditorUtils::FindEventGraph(Blueprint);

	FString Json = TEXT("{\"name\":\"") + BlueprintJsonEscape(Blueprint->GetName());
	Json += TEXT("\",\"path\":\"") + BlueprintJsonEscape(Blueprint->GetPathName());
	Json += TEXT("\",\"class\":\"") + BlueprintJsonEscape(Blueprint->GetClass()->GetName());
	Json += TEXT("\",\"graphs\":[");

	bool bFirst = true;
	for (UEdGraph* Graph : Graphs)
	{
		if (!Graph)
		{
			continue;
		}
		if (!bFirst)
		{
			Json += TEXT(",");
		}
		bFirst = false;
		Json += TEXT("{\"name\":\"") + BlueprintJsonEscape(Graph->GetName());
		Json += TEXT("\",\"type\":\"");
		Json += Graph == EventGraph ? TEXT("EventGraph") : TEXT("Function");
		Json += TEXT("\"}");
	}
	Json += TEXT("],\"graph_count\":") + FString::FromInt(Graphs.Num());

	Json += TEXT(",\"nodes\":[");
	bFirst = true;
	int32 NodeCount = 0;
	for (UEdGraph* Graph : Graphs)
	{
		if (!Graph)
		{
			continue;
		}
		for (UEdGraphNode* Node : Graph->Nodes)
		{
			if (!Node)
			{
				continue;
			}
			if (!bFirst)
			{
				Json += TEXT(",");
			}
			bFirst = false;
			++NodeCount;
			Json += TEXT("{\"name\":\"") + BlueprintJsonEscape(Node->GetName());
			Json += TEXT("\",\"class\":\"") + BlueprintJsonEscape(Node->GetClass()->GetName());
			Json += TEXT("\",\"title\":\"") + BlueprintJsonEscape(Node->NodeComment);
			Json += TEXT("\"}");
		}
	}
	Json += TEXT("],\"node_count\":") + FString::FromInt(NodeCount);

	Json += TEXT(",\"variables\":[");
	bFirst = true;
	for (const FBPVariableDescription& Variable : Blueprint->NewVariables)
	{
		if (!bFirst)
		{
			Json += TEXT(",");
		}
		bFirst = false;
		Json += TEXT("{\"name\":\"") + BlueprintJsonEscape(Variable.VarName.ToString());
		Json += TEXT("\",\"type\":\"") + BlueprintJsonEscape(Variable.VarType.PinCategory.ToString());
		Json += TEXT("\"}");
	}
	Json += TEXT("]}");
	return Json;
}

FString UCliAnythingBridgeLibrary::AddBlueprintFunction(UBlueprint* Blueprint, const FString& FunctionName)
{
	if (!Blueprint)
	{
		return BlueprintJsonError(TEXT("Blueprint is null."));
	}
	if (FunctionName.IsEmpty())
	{
		return BlueprintJsonError(TEXT("Function name is required."));
	}
	if (FindBlueprintGraph(Blueprint, FunctionName))
	{
		return BlueprintJsonError(TEXT("Function graph already exists: ") + FunctionName);
	}

	Blueprint->Modify();
	UEdGraph* Graph = FBlueprintEditorUtils::CreateNewGraph(
		Blueprint,
		FName(*FunctionName),
		UEdGraph::StaticClass(),
		UEdGraphSchema_K2::StaticClass()
	);
	if (!Graph)
	{
		return BlueprintJsonError(TEXT("Failed to create function graph: ") + FunctionName);
	}

	FBlueprintEditorUtils::AddFunctionGraph<UClass>(
		Blueprint,
		Graph,
		true,
		nullptr
	);
	Graph->Modify();
	Blueprint->MarkPackageDirty();

	return TEXT("{\"status\":\"ok\",\"action\":\"add_function\",\"function\":\"")
		+ BlueprintJsonEscape(FunctionName)
		+ TEXT("\",\"graph_name\":\"")
		+ BlueprintJsonEscape(Graph->GetName())
		+ TEXT("\"}");
}

FString UCliAnythingBridgeLibrary::RemoveBlueprintFunction(UBlueprint* Blueprint, const FString& FunctionName)
{
	if (!Blueprint)
	{
		return BlueprintJsonError(TEXT("Blueprint is null."));
	}
	UEdGraph* Graph = FindBlueprintGraph(Blueprint, FunctionName);
	if (!Graph || !Blueprint->FunctionGraphs.Contains(Graph))
	{
		return BlueprintJsonError(TEXT("Function graph not found: ") + FunctionName);
	}

	Blueprint->Modify();
	FBlueprintEditorUtils::RemoveGraph(Blueprint, Graph);
	Blueprint->MarkPackageDirty();
	return TEXT("{\"status\":\"ok\",\"action\":\"remove_function\",\"function\":\"")
		+ BlueprintJsonEscape(FunctionName)
		+ TEXT("\"}");
}

FString UCliAnythingBridgeLibrary::AddBlueprintVariable(UBlueprint* Blueprint, const FString& VariableName, const FString& VariableType)
{
	if (!Blueprint)
	{
		return BlueprintJsonError(TEXT("Blueprint is null."));
	}
	if (VariableName.IsEmpty())
	{
		return BlueprintJsonError(TEXT("Variable name is required."));
	}

	FEdGraphPinType PinType;
	if (!MakeBlueprintPinType(VariableType, PinType))
	{
		return BlueprintJsonError(
			TEXT("Unknown variable type: ") + VariableType
			+ TEXT(". Valid types: bool, int, float, string, text, name, vector, rotator, transform")
		);
	}

	Blueprint->Modify();
	if (!FBlueprintEditorUtils::AddMemberVariable(Blueprint, FName(*VariableName), PinType))
	{
		return BlueprintJsonError(TEXT("add_member_variable returned False for: ") + VariableName);
	}
	Blueprint->MarkPackageDirty();

	return TEXT("{\"status\":\"ok\",\"action\":\"add_variable\",\"variable\":\"")
		+ BlueprintJsonEscape(VariableName)
		+ TEXT("\",\"type\":\"")
		+ BlueprintJsonEscape(VariableType)
		+ TEXT("\"}");
}

FString UCliAnythingBridgeLibrary::RemoveBlueprintVariable(UBlueprint* Blueprint, const FString& VariableName)
{
	if (!Blueprint)
	{
		return BlueprintJsonError(TEXT("Blueprint is null."));
	}
	const FName Name(*VariableName);
	if (FBlueprintEditorUtils::FindNewVariableIndex(Blueprint, Name) == INDEX_NONE)
	{
		return BlueprintJsonError(TEXT("Member variable not found: ") + VariableName);
	}

	Blueprint->Modify();
	FBlueprintEditorUtils::RemoveMemberVariable(Blueprint, Name);
	Blueprint->MarkPackageDirty();
	return TEXT("{\"status\":\"ok\",\"action\":\"remove_variable\",\"variable\":\"")
		+ BlueprintJsonEscape(VariableName)
		+ TEXT("\"}");
}

FString UCliAnythingBridgeLibrary::RemoveUnusedBlueprintVariables(UBlueprint* Blueprint)
{
	if (!Blueprint)
	{
		return BlueprintJsonError(TEXT("Blueprint is null."));
	}

	TArray<FName> UnusedVariables;
	for (const FBPVariableDescription& Variable : Blueprint->NewVariables)
	{
		if (!FBlueprintEditorUtils::IsVariableUsed(Blueprint, Variable.VarName))
		{
			UnusedVariables.Add(Variable.VarName);
		}
	}

	if (UnusedVariables.Num() > 0)
	{
		Blueprint->Modify();
		for (const FName& VariableName : UnusedVariables)
		{
			FBlueprintEditorUtils::RemoveMemberVariable(Blueprint, VariableName);
		}
		Blueprint->MarkPackageDirty();
	}

	return TEXT("{\"status\":\"ok\",\"action\":\"remove_unused_variables\",\"removed_count\":")
		+ FString::FromInt(UnusedVariables.Num())
		+ TEXT("}");
}

FString UCliAnythingBridgeLibrary::RenameBlueprintGraph(UBlueprint* Blueprint, const FString& OldName, const FString& NewName)
{
	if (!Blueprint)
	{
		return BlueprintJsonError(TEXT("Blueprint is null."));
	}
	if (NewName.IsEmpty())
	{
		return BlueprintJsonError(TEXT("New graph name is required."));
	}
	UEdGraph* Graph = FindBlueprintGraph(Blueprint, OldName);
	if (!Graph)
	{
		return BlueprintJsonError(TEXT("Graph not found: ") + OldName);
	}
	if (FindBlueprintGraph(Blueprint, NewName))
	{
		return BlueprintJsonError(TEXT("Graph already exists: ") + NewName);
	}

	Blueprint->Modify();
	FBlueprintEditorUtils::RenameGraph(Graph, NewName);
	Blueprint->MarkPackageDirty();
	return TEXT("{\"status\":\"ok\",\"action\":\"rename_graph\",\"old_name\":\"")
		+ BlueprintJsonEscape(OldName)
		+ TEXT("\",\"new_name\":\"")
		+ BlueprintJsonEscape(Graph->GetName())
		+ TEXT("\"}");
}

FString UCliAnythingBridgeLibrary::CompileBlueprint(UBlueprint* Blueprint)
{
	if (!Blueprint)
	{
		return BlueprintJsonError(TEXT("Blueprint is null."));
	}

	FKismetEditorUtilities::CompileBlueprint(Blueprint);
	if (Blueprint->Status == BS_Error)
	{
		return BlueprintJsonError(TEXT("Blueprint compile failed: ") + Blueprint->GetPathName());
	}
	return TEXT("{\"status\":\"ok\",\"action\":\"compile\"}");
}
