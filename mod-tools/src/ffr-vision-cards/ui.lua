-- Independent equipment row, owned-card grid and native skill-panel card details.
local M={}
local state,active,pc,world
local rows,buttons,textures,heads={},{},{},{}
local compacted={}
local skillPanels={}
local nativeFont
local GRID_COLUMNS,GRID_PAGE=3,9
local scan=0
local pendingClick
local pendingWidget
local retain
local keyState={}
local function valid(o) return o and o:IsValid() end
local function log(s) print('[FFRVisionCards] '..s..'\n') end
local function same(a,b) return valid(a) and valid(b) and a:GetAddress()==b:GetAddress() end
local function lib(name) return StaticFindObject('/Script/Engine.Default__'..name) end
local function text(s) return FText(tostring(s)) end
local function object(kind,owner)
    local o=StaticConstructObject(StaticFindObject('/Script/UMG.'..kind),owner.WidgetTree)
    assert(valid(o),'Cannot create '..kind)
    return o
end
local function class(path)
    local name=path:match('([^/]+)$')
    local cls=StaticFindObject(path..'.'..name..'_C')
    if not valid(cls) then
        local sys=lib('KismetSystemLibrary')
        cls=sys:LoadClassAsset_Blocking(sys:Conv_SoftClassPathToSoftClassRef(sys:MakeSoftClassPath(path..'.'..name..'_C')))
    end
    assert(valid(cls),'Cannot load '..path)
    return cls
end
local function widget(path)
    local cls=class(path)
    local o=StaticFindObject('/Script/UMG.Default__WidgetBlueprintLibrary'):Create(world,cls,pc)
    assert(valid(o),'Cannot create '..path)
    return o
end
local function label(owner,value,size)
    local o=object('TextBlock',owner)
    o:SetText(text(value));o:SetAutoWrapText(true)
    if not nativeFont or not valid(nativeFont) then
        for _,head in ipairs(FindAllOf('WBP_SystemSubhead_C') or {}) do
            if valid(head.Text_Title) then nativeFont=head.Text_Title;break end
        end
    end
    -- Copy the complete native struct first (including its unreflected shared
    -- font data), then resize our copy rather than the donor widget's field.
    if valid(nativeFont) then o:SetFont(nativeFont.Font) end
    local font=o.Font;font.Size=size or font.Size;o:SetFont(font)
    return o
end
local function box(owner,content,w,h)
    local o=object('SizeBox',owner)
    if w then o:SetWidthOverride(w) end
    if h then o:SetHeightOverride(h) end
    o:SetContent(content);return o
end
local function texture(path)
    if not path then return nil end
    if not valid(textures[path]) then
        textures[path]=lib('KismetRenderingLibrary'):ImportFileAsTexture2D(world,path)
    end
    return textures[path]
end
local function art(owner,path,w,h)
    local img=object('Image',owner)
    local tex=texture(path)
    if valid(tex) then img:SetBrushFromTexture(tex,false) end
    return img,box(owner,img,w,h)
end
local function card_back(owner,w,h)
    local img,frame=art(owner,state.catalog.icon,w,h)
    -- The supplied FFBE card-back reference remains unmodified on disk. Crop
    -- its surrounding screenshot in the UI brush, then tilt it in the bubble.
    local brush=img.Brush
    brush.UVRegion={min={X=0.074,Y=0.058},max={X=0.886,Y=0.930},bIsValid=true}
    img:SetBrush(brush)
    img:SetRenderTransformAngle(-12)
    return img,frame
end
local function compact(widget)
    -- Native menus nest dozens of panels. Walk iteratively so reflected Lua
    -- calls never exhaust the bridge's C stack inside a recursive traversal.
    local textClass=StaticFindObject('/Script/UMG.TextBlock')
    local userClass=StaticFindObject('/Script/UMG.UserWidget')
    local panelClass=StaticFindObject('/Script/UMG.PanelWidget')
    local queue,seen={widget},{}
    while #queue>0 do
        local current=table.remove(queue)
        if valid(current) then
            local address=current:GetAddress()
            if not seen[address] then
                seen[address]=true
                if current:IsA(textClass) and not compacted[address] then
                    local font=current.Font;font.Size=math.max(10,font.Size-1);current:SetFont(font)
                    compacted[address]=current
                end
                if current:IsA(userClass) then
                    if valid(current.WidgetTree) then queue[#queue+1]=current.WidgetTree.RootWidget end
                elseif current:IsA(panelClass) then
                    for i=0,current:GetChildrenCount()-1 do queue[#queue+1]=current:GetChildAt(i) end
                end
            end
        end
    end
end
local function button(owner,content,callback)
    local o=widget('/Game/UI/Foundation/Button/WBP_ListEntryButtonBase')
    o.NamedSlot_Content_87:SetContent(content)
    buttons[o:GetAddress()]={widget=o,click=callback}
    return o
end
local function stats(card)
    if not card then return 'No card equipped' end
    local s=card.stats
    return string.format('MAX LEVEL %d\n\nHP    +%d\nMP    +%d\nATK   +%d\nDEF   +%d\nMAG   +%d\nSPR   +%d',card.maxLevel,s.hp,s.mp,s.atk,s.def,s.mag,s.spr)
end
local function row_name(row)
    local card=state.cards[state:get(row.screen.VM_ActionEquipment.TargetUnitId)]
    row.name:SetText(text(card and card.name or 'None'))
end
local function restore_equipment_target(row)
    local parent=row.parent
    if not valid(parent) then return end
    -- The stock slot-click delegate may have pushed its native item picker
    -- before our deferred callback runs. Return to this independent slot's
    -- equipment menu, including its Back stack, before showing/restoring it.
    for _=1,8 do
        if same(parent:BP_GetInputTargetWidget(),row.screen) then return end
        if not parent:PopInputTargetWidget() then break end
    end
    if not same(parent:BP_GetInputTargetWidget(),row.screen) then parent:PushInputTargetWidget(row.screen) end
end
local function close()
    if not active then return end
    active.window:RemoveFromParent()
    local row=active.row
    FFRVisionCardsSetSelectorOpen(false)
    for _,saved in ipairs(active.suspended) do
        if valid(saved.widget) then
            saved.widget.bCanReceiveInput=saved.receive
            saved.widget.IsCanInput=saved.input
        end
    end
    active=nil
    if row and valid(row.screen) then
        restore_equipment_target(row)
        row.screen:SetIsInputTarget(true)
        retain(row)
        row_name(row)
        row.button:CapturingFocus()
    end
end
local function render()
    local a=active
    if not a then return end
    a.grid:ClearChildren();a.images={};a.animationIndex=1;a.elapsed=0;a.lastTime=nil
    local first=math.floor((a.index-1)/GRID_PAGE)*GRID_PAGE+1
    -- Reserve every cell, including the last row: one or two owned cards must
    -- not cause UniformGridPanel to stretch them across the whole selector.
    for cell=0,GRID_PAGE-1 do
        a.grid:AddChildToUniformGrid(box(a.window,nil,208,256),math.floor(cell/GRID_COLUMNS),cell%GRID_COLUMNS)
    end
    for i=first,math.min(first+GRID_PAGE-1,#a.cards) do
        local card=a.cards[i]
        local column=object('VerticalBox',a.window)
        local img,frame=art(a.window,card.static,144,192)
        column:AddChildToVerticalBox(frame):SetHorizontalAlignment(2)
        local name=label(a.window,card.name,20)
        local nameBox=box(a.window,name,184,48)
        nameBox:SetClipping(1)
        column:AddChildToVerticalBox(nameBox)
        a.images[i]=img
        local tile=object('Border',a.window)
        tile:SetPadding({Left=4,Top=4,Right=4,Bottom=4})
        tile:SetBrushColor(i==a.index and {R=0.54,G=0.39,B=0.12,A=1} or {R=0.025,G=0.055,B=0.075,A=1})
        tile:SetContent(column)
        local b=button(a.window,box(a.window,tile,196,248),function()
            if active~=a then return end
            if a.index==i then M.equip() else a.index=i;render() end
        end)
        b:SetRenderOpacity(i==a.index and 1.0 or 0.64)
        local slot=a.grid:AddChildToUniformGrid(b,math.floor((i-first)/GRID_COLUMNS),(i-first)%GRID_COLUMNS)
        slot:SetHorizontalAlignment(2);slot:SetVerticalAlignment(0)
    end
    local selected=a.cards[a.index]
    a.title:SetText(text(selected.name))
    a.stat:SetText(text(stats(selected.id~=0 and selected or nil)))
    a.hint:SetText(text(string.format('A  Equip    B  Close    D-pad  Select                 %d / %d',math.floor((a.index-1)/GRID_PAGE)+1,math.ceil(#a.cards/GRID_PAGE))))
end
function M.equip()
    local a=active
    if not a then return end
    local ok,why=pcall(function()
        state:equip(a.unit,a.cards[a.index].id)
        local units=StaticFindObject('/Script/mucha.Default__CPP_BFL_Unit')
        local p=units:GetPlayableUnitParameterObj(a.unit)
        if valid(p) then
            units:SetPlayableUnitHitPoint(a.unit,math.min(p:GetHitPoint(),p:GetMaxHitPoint()))
            units:SetPlayableUnitMagicPoint(a.unit,math.min(p:GetMagicPoint(),p:GetMaxMagicPoint()))
        end
        units:ExecuteUnitActionUpdate(a.unit)
    end)
    if ok then close() else a.hint:SetText(text(tostring(why):gsub('^.-:%d+: ',''))) end
end
function M.open(row,unit)
    if active then return end
    local w=widget('/Game/UI/Common/Window/WBP_Cmn_Window')
    local root=object('VerticalBox',w)
    local title=label(w,'Vision Cards',28);root:AddChildToVerticalBox(title)
    local horizontal=object('HorizontalBox',w);root:AddChildToVerticalBox(horizontal)
    local grid=object('UniformGridPanel',w)
    local gridBox=box(w,grid,624,768)
    horizontal:AddChildToHorizontalBox(gridBox)
    local side=object('VerticalBox',w)
    horizontal:AddChildToHorizontalBox(box(w,side,300,nil))
    local stat=label(w,'',22);side:AddChildToVerticalBox(stat)
    local hint=label(w,'',18);root:AddChildToVerticalBox(hint)
    local background=object('Border',w)
    background:SetBrushColor({R=0.015,G=0.035,B=0.05,A=1})
    background:SetPadding({Left=24,Top=20,Right=24,Bottom=20})
    background:SetContent(root)
    w.Window_Content:SetContent(background)
    local cards={{id=0,name='Remove card',description='',static=state.catalog.removeIcon}}
    for _,card in ipairs(state:available(unit)) do cards[#cards+1]=card end
    local selected=state:get(unit)
    local index=1
    for i,c in ipairs(cards) do if c.id==selected then index=i end end
    active={window=w,row=row,unit=unit,cards=cards,index=index,grid=grid,gridBox=gridBox,
            title=title,stat=stat,hint=hint,suspended={}}
    FFRVisionCardsSetSelectorOpen(true)
    for _,name in ipairs({'Gamepad_FaceButton_Right','Gamepad_FaceButton_Bottom',
                         'Gamepad_DPad_Left','Gamepad_DPad_Right','Gamepad_DPad_Up','Gamepad_DPad_Down','Escape','Enter','Left','Right','Up','Down'}) do
        keyState[name]=pc:IsInputKeyDown({KeyName=FName(name)})
    end
    if row then
        row.screen:SetIsInputTarget(false)
        local outer=row.screen:GetOuter()
        while valid(outer) do
            if outer:IsA(StaticFindObject('/Script/EnhancedUI.CPP_EU_WBP_Activatable')) then
                if not valid(row.parent) then row.parent=outer end
                if same(outer,row.parent) then restore_equipment_target(row) end
                active.suspended[#active.suspended+1]={widget=outer,receive=outer.bCanReceiveInput,input=outer.IsCanInput}
                outer.bCanReceiveInput=false;outer.IsCanInput=false
            end
            outer=outer:GetOuter()
        end
    end
    w:SetDesiredSizeInViewport({X=1040,Y=880})
    w:SetAlignmentInViewport({X=0.5,Y=0.5})
    local viewport=StaticFindObject('/Script/UMG.Default__WidgetLayoutLibrary'):GetViewportSize(world)
    local scale=StaticFindObject('/Script/UMG.Default__WidgetLayoutLibrary'):GetViewportScale(world)
    w:SetPositionInViewport({X=viewport.X/(2*scale),Y=viewport.Y/(2*scale)},false)
    w:AddToViewport(10000)
    render()
    log('Card grid opened for unit '..unit)
end
local function attach(screen)
    local key=screen:GetAddress()
    if rows[key] then return end
    if not valid(screen.VM_ActionEquipment) or screen.VM_ActionEquipment.TargetUnitId<=0 then return end
    local row={screen=screen}
    row.section=object('VerticalBox',screen)
    local nativeHead=screen.WBP_VisionList.WBP_SystemSubhead
    row.heading=StaticFindObject('/Script/UMG.Default__WidgetBlueprintLibrary'):Create(world,nativeHead:GetClass(),pc)
    row.heading:SetTitle(text('VISION CARD'))
    row.section:AddChildToVerticalBox(row.heading)
    row.name=label(screen,'None',19)
    row.name:SetAutoWrapText(false)
    local line=object('HorizontalBox',screen)
    local accent=object('Border',screen)
    accent:SetBrushColor({R=0.42,G=0.76,B=0.82,A=1})
    line:AddChildToHorizontalBox(box(screen,accent,4,nil))
    local _,icon=card_back(screen,22,29)
    local iconSlot=line:AddChildToHorizontalBox(icon)
    iconSlot:SetPadding({Left=7,Top=3,Right=9,Bottom=3});iconSlot:SetVerticalAlignment(2)
    local nameSlot=line:AddChildToHorizontalBox(row.name);nameSlot:SetVerticalAlignment(2)
    local blue=object('Border',screen)
    blue:SetBrushColor({R=0.035,G=0.13,B=0.18,A=0.9})
    blue:SetPadding({Left=0,Top=0,Right=6,Bottom=0});blue:SetContent(line)
    row.button=button(screen,box(screen,blue,nil,38),function() M.open(row,screen.VM_ActionEquipment.TargetUnitId) end)
    -- Native RetainEntryList binds this relay for every normal row. Without it
    -- focus can be drawn on the card while navigation/confirm still target the
    -- previous native equipment row.
    row.button:BindToAllButtonEventByName(screen,FName('BroadcastButtonEvent'))
    row.section:AddChildToVerticalBox(row.button)
    local panel=screen.VerticalBox_List
    local children={}
    for i=0,panel:GetChildrenCount()-1 do children[#children+1]=panel:GetChildAt(i) end
    panel:ClearChildren()
    local inserted=false
    for _,child in ipairs(children) do
        panel:AddChildToVerticalBox(child)
        if same(child,screen.WBP_VisionList) then panel:AddChildToVerticalBox(row.section);inserted=true end
    end
    assert(inserted,'Vision section missing from equipment layout')
    compact(screen)
    rows[key]=row;row_name(row)
    log('Vision card equipment row inserted')
end
retain=function(row)
    local s=row.screen
    local entries={}
    local vision=s.WBP_VisionList:GetItemList()
    local equipment=s.WBP_ItemLIst:GetItemList()
    local function count(v) if type(v)=='table' then return #v else return v:GetArrayNum() end end
    local insertAt=count(equipment)+count(vision)
    if insertAt==0 then entries[#entries+1]=row.button end
    local originalIndex=0
    s.EntryList:ForEach(function(_,value)
        local item=value:get()
        if not same(item,row.button) then
            entries[#entries+1]=item
            originalIndex=originalIndex+1
            if originalIndex==insertAt then entries[#entries+1]=row.button end
        end
    end)
    s.EntryList=entries
end
local function pressed(...)
    local hit=false
    for _,name in ipairs({...}) do
        local down=pc:IsInputKeyDown({KeyName=FName(name)})
        if down and not keyState[name] then hit=true end
        keyState[name]=down
    end
    return hit
end
local function attach_skill_panel(layout)
    local key=layout:GetAddress()
    if skillPanels[key] then return end
    local actions=layout.WBP_UnitSkillPanel_ActionList
    if not valid(actions) or not valid(layout.VM_UnitSkillPanel) then return end
    local list=actions.WidgetSwitcher_0
    local parent=list:GetParent()
    if not valid(parent) then return end
    local root=object('VerticalBox',actions)
    list:RemoveFromParent()
    parent:SetContent(root)
    root:AddChildToVerticalBox(list):SetSize({SizeRule=1,Value=1})
    local section=object('VerticalBox',actions)
    local head=StaticFindObject('/Script/UMG.Default__WidgetBlueprintLibrary'):Create(world,actions.WBP_SystemSubhead:GetClass(),pc)
    head:SetTitle(text('VISION CARD'))
    section:AddChildToVerticalBox(head)
    local body=object('HorizontalBox',actions)
    section:AddChildToVerticalBox(body)
    local img,frame=art(actions,nil,288,384)
    body:AddChildToHorizontalBox(frame)
    local info=object('VerticalBox',actions)
    local infoSlot=body:AddChildToHorizontalBox(info)
    infoSlot:SetPadding({Left=20,Top=8,Right=0,Bottom=0});infoSlot:SetSize({SizeRule=1,Value=1})
    local name=label(actions,'',24);info:AddChildToVerticalBox(name)
    local stat=label(actions,'',22)
    info:AddChildToVerticalBox(stat):SetPadding({Left=0,Top=16,Right=0,Bottom=0})
    root:AddChildToVerticalBox(section):SetPadding({Left=0,Top=14,Right=0,Bottom=0})
    skillPanels[key]={layout=layout,image=img,name=name,stat=stat,section=section}
    log('Vision card section attached to native skill details')
end
local function animate(view,card,target,now)
    if not card or not card.frames or #card.frames<2 then return end
    view.animationIndex=view.animationIndex or 1
    view.elapsed=(view.elapsed or 0)+math.max(0,now-(view.lastTime or now))
    view.lastTime=now
    local previous=view.animationIndex
    while view.elapsed>=card.frames[view.animationIndex].duration do
        view.elapsed=view.elapsed-card.frames[view.animationIndex].duration
        view.animationIndex=view.animationIndex%#card.frames+1
    end
    if view.animationIndex~=previous then
        local tex=texture(card.frames[view.animationIndex].path)
        if valid(target) and valid(tex) then target:SetBrushFromTexture(tex,false) end
    end
end
local function update_skill_panels(now)
    for key,view in pairs(skillPanels) do
        if not valid(view.layout) then skillPanels[key]=nil
        elseif view.layout:IsVisible() then
            local unit=view.layout.VM_UnitSkillPanel.UnitId
            local id=state:get(unit)
            local card=state.cards[id]
            if view.cardId~=id or view.unit~=unit then
                view.cardId=id;view.unit=unit;view.animationIndex=1;view.elapsed=0;view.lastTime=now
                view.name:SetText(text(card and card.name or 'None'))
                local value='No card equipped'
                if card then
                    local s=card.stats
                    value=string.format('MAX LEVEL %d\n\nHP    +%d\nMP    +%d\nATK   +%d\nDEF   +%d\nMAG   +%d\nSPR   +%d',card.maxLevel,s.hp,s.mp,s.atk,s.def,s.mag,s.spr)
                end
                view.stat:SetText(text(value))
                local tex=texture(card and card.static or state.catalog.removeIcon)
                if valid(tex) then view.image:SetBrushFromTexture(tex,false) end
            end
            animate(view,card,view.image,now)
        else view.lastTime=now end
    end
end
function M.tick()
    if not valid(pc) then
        pc=FindFirstOf('PlayerController')
        if not valid(pc) then return end
        world=pc
    end
    if pendingWidget then
        local current=pendingWidget;pendingWidget=nil
        while valid(current) do
            local entry=buttons[current:GetAddress()]
            if entry then pendingClick=entry.click;break end
            current=current:GetOuter()
        end
    end
    if pendingClick then
        local callback=pendingClick;pendingClick=nil
        callback()
    end
    scan=scan+1
    if scan%40==1 or FFRVisionCardsNeedsRefresh then
        local updateViews=FFRVisionCardsNeedsRefresh
        FFRVisionCardsNeedsRefresh=false
        state:refresh(updateViews)
        for key,row in pairs(rows) do if not valid(row.screen) then rows[key]=nil end end
        for _,screen in ipairs(FindAllOf('WBP_UnitEquippedList_C') or {}) do
            if screen:IsVisible() then attach(screen) end
        end
        for _,row in pairs(rows) do if valid(row.screen) then retain(row);row_name(row);compact(row.screen) end end
        for _,layout in ipairs(FindAllOf('WBP_UnitSkillLayout_C') or {}) do
            if layout:IsVisible() then attach_skill_panel(layout) end
        end
        for _,head in ipairs(FindAllOf('CPP_WC_ObjectHead') or {}) do
            local owner=head:GetOwner()
            if valid(owner) and owner:GetFullName():find('NPC_VisionCards',1,true) then
                local view=head:GetUserWidgetObject()
                if valid(view) and not heads[view:GetAddress()] then
                    local original=view.Border_Content:GetContent()
                    original:RemoveFromParent()
                    local overlay=object('Overlay',view)
                    overlay:AddChildToOverlay(original)
                    local img,frame=card_back(view,24,32)
                    local mask=object('Border',view)
                    mask:SetBrushColor({R=0.025,G=0.025,B=0.025,A=1})
                    mask:SetPadding({Left=1,Top=0,Right=1,Bottom=0});mask:SetContent(frame)
                    mask:SetRenderTranslation({X=0,Y=-4})
                    local slot=overlay:AddChildToOverlay(mask)
                    slot:SetHorizontalAlignment(2);slot:SetVerticalAlignment(2)
                    view.Border_Content:SetContent(overlay)
                    heads[view:GetAddress()]={widget=view,image=img}
                    log('Mitra merchant card icon attached')
                end
            end
        end
    end
    local now=lib('GameplayStatics'):GetRealTimeSeconds(world)*1000
    update_skill_panels(now)
    if not active then return end
    local a=active
    if pressed('Gamepad_FaceButton_Right','Escape') then
        close()
        return
    end
    if pressed('Gamepad_FaceButton_Bottom','Enter') then M.equip();return end
    do
        local index=a.index
        if pressed('Gamepad_DPad_Left','Left') then index=index-1 end
        if pressed('Gamepad_DPad_Right','Right') then index=index+1 end
        if pressed('Gamepad_DPad_Up','Up') then index=index-GRID_COLUMNS end
        if pressed('Gamepad_DPad_Down','Down') then index=index+GRID_COLUMNS end
        index=math.max(1,math.min(#a.cards,index))
        if index~=a.index then a.index=index;render() end
    end
    animate(a,a.cards[a.index],a.images[a.index],now)
end
function M.start(model)
    state=model
    class('/Game/UI/Foundation/Button/WBP_ButtonBase')
    RegisterHook('/Game/UI/Foundation/Button/WBP_ButtonBase.WBP_ButtonBase_C:BP_OnClicked',function(context)
        pendingWidget=context:get()
    end)
    -- Keep the scheduler and widget callbacks on the same thread. An async
    -- Lua timer can race the shared Lua heap while a card window is rebuilding.
    LoopInGameThreadWithDelay(25,function()
        local ok,why=pcall(M.tick)
        if not ok and M.lastError~=tostring(why) then M.lastError=tostring(why);log('UI error: '..M.lastError) end
        return false
    end)
end
M.close=close
function M.probe_town()
    close()
    local merchant,donor
    for _,npc in ipairs(FindAllOf('CPP_MapUnit_NPC') or {}) do
        if npc.m_UniqueId==9470 then merchant=npc end
        if npc.m_UniqueId==24 then donor=npc end
    end
    assert(valid(merchant) and valid(donor),'Both merchants must be present')
    local a,b=merchant:K2_GetActorLocation(),donor:K2_GetActorLocation()
    log(string.format('Merchant position %.1f %.1f %.1f; accessory %.1f %.1f %.1f',a.X,a.Y,a.Z,b.X,b.Y,b.Z))
    local player=StaticFindObject('/Script/mucha.Default__CPP_BFL_Map'):GetPlayerMapUnit()
    assert(valid(player),'Town player missing')
    player:K2_SetActorLocation({X=b.X-140,Y=b.Y-80,Z=b.Z},false,{},true)
    local gameplay=lib('GameplayStatics')
    local position={X=b.X-850,Y=(a.Y+b.Y)/2,Z=b.Z+650}
    local transform={Rotation={X=0,Y=0,Z=0,W=1},Translation=position,Scale3D={X=1,Y=1,Z=1}}
    local camera=gameplay:BeginDeferredActorSpawnFromClass(world,StaticFindObject('/Script/Engine.CameraActor'),transform,1,pc,0)
    gameplay:FinishSpawningActor(camera,transform,0)
    camera:K2_SetActorRotation(lib('KismetMathLibrary'):FindLookAtRotation(position,{X=b.X,Y=(a.Y+b.Y)/2,Z=b.Z+55}),true)
    camera.CameraComponent:SetFieldOfView(45)
    pc:SetViewTargetWithBlend(camera,0,0,0,false)
    ExecuteInGameThreadWithDelay(2000,function()
        ExecuteInGameThread(function()
            local ok,why=pcall(function()
                local left,right={},{}
                pc:ProjectWorldLocationToScreen(a,left,false);pc:ProjectWorldLocationToScreen(b,right,false)
                log('Merchant screen X='..tostring(left.X)..'; accessory screen X='..tostring(right.X))
                assert(left.X<right.X,'Card merchant must be left of accessory merchant')
                player:K2_SetActorLocation({X=b.X-140,Y=a.Y,Z=b.Z},true,{},false)
                local reached=player:K2_GetActorLocation()
                assert(math.abs(reached.Y-a.Y)<30,'Card merchant approach is blocked')
                log('Merchant walking approach passed')
                lib('KismetSystemLibrary'):ExecuteConsoleCommand(world,'Shot showui',pc)
            end)
            if not ok then log('UI error: '..tostring(why)) end
        end)
    end)
end
function M.probe()
    close()
    local menu=FindFirstOf('CPP_MainMenuSubsystem')
    assert(valid(menu),'Main menu subsystem missing')
    menu:SetLastSelectedTargetUnitId(1001)
    menu:SetScene({TagName=FName('UI.MainMenu.Scene.ActionEquip')},{})
    log('Native action equipment scene requested')
end
function M.probe_live()
    -- Offscreen test copies are unfocused. Reproduce a foreground game's input
    -- state before sending events through its real global input handler.
    FindFirstOf('CPP_GameWidgetManagerSubsystem'):OnApplicationFocusChanged(true)
    local input=FindFirstOf('CPP_GameWidgetInputManager')
    local outer=input.GameLayoutWidget:GetInputTargetLayer():GetActiveWidget()
    local scene=outer:BP_GetInputTargetWidget():GetActiveWidget()
    log('Before character confirm '..scene:BP_GetInputTargetWidget():GetFullName())
    input:HandleInputDecide({})
    log('After character confirm '..scene:BP_GetInputTargetWidget():GetFullName())
    local found=false
    for _,row in pairs(rows) do
        if row.screen:IsVisible() and row.screen.VM_ActionEquipment.TargetUnitId==1001 then
            local total=row.screen.EntryList:GetArrayNum()
            if total>1 then
                found=true
                log('Live equipment navigation entries='..total)
                local target
                row.screen.EntryList:ForEach(function(i,value) if same(value:get(),row.button) then target=i-1 end end)
                assert(target,'Live card slot missing')
                lib('KismetSystemLibrary'):ExecuteConsoleCommand(world,'Shot showui',pc)
                log('Native styled equipment screenshot requested')
                row.screen:SetAsInputTarget()
                row.screen:SetFocusedItemByIndex(target-1)
                log('Navigation before card='..row.screen:GetFocusedItemIndex(2)..'; target='..target)
                row.screen:InputDirection(3,0)
                log('Navigation after Down='..row.screen:GetFocusedItemIndex(2))
                assert(row.screen:GetFocusedItemIndex(2)==target,'Down did not reach the card slot')
                row.screen:InputDirection(3,0)
                assert(row.screen:GetFocusedItemIndex(2)==target+1,'Down did not leave the card slot')
                row.screen:InputDirection(2,0)
                assert(row.screen:GetFocusedItemIndex(2)==target,'Up did not return to the card slot')
                ExecuteInGameThreadWithDelay(2000,function()
                    ExecuteInGameThread(function()
                        local input=FindFirstOf('CPP_GameWidgetInputManager')
                        assert(valid(input),'Native menu input manager missing')
                        input:HandleInputDecide({});M.tick()
                        assert(active,'Live card slot did not open')
                        assert(#active.cards==11,'Owned grid lost purchased cards')
                        log('Native Down/Up/Confirm card navigation passed')
                        for i,card in ipairs(active.cards) do if card.id==401000401 then active.index=i end end
                        render()
                        lib('KismetSystemLibrary'):ExecuteConsoleCommand(world,'Shot showui',pc)
                    end)
                end)
            end
        end
    end
    assert(found,'Native equipment scene was not populated')
    ExecuteInGameThreadWithDelay(5000,function()
        ExecuteInGameThread(function()
            assert(active,'Card grid closed before layout check')
            local input=FindFirstOf('CPP_GameWidgetInputManager')
            input:HandleInputDetail({});input:HandleInput_ActionEquip_Detail({})
            assert(active,'Details input disturbed the card selector')
            local original=active.cards
            active.cards={original[1],original[active.index]};active.index=2;render()
            assert(active.grid:GetChildrenCount()==11,'Sparse grid must retain nine fixed cells')
            assert(same(active.images[1].Brush.ResourceObject,texture(state.catalog.removeIcon)),'Remove-card artwork mismatch')
            assert(same(active.title.Font.FontObject,nativeFont.Font.FontObject),'Selector did not use the native font')
            lib('KismetSystemLibrary'):ExecuteConsoleCommand(world,'Shot showui',pc)
            active.probeCards=original
            log('Three-column sparse grid, remove artwork and native font passed')
        end)
    end)
    ExecuteInGameThreadWithDelay(7000,function()
        ExecuteInGameThread(function()
            assert(active,'Card selection lost before equip check')
            local row=active.row
            local units=StaticFindObject('/Script/mucha.Default__CPP_BFL_SaveDataUnit')
            local accessories={units:GetEquipmentId(active.unit,3,0),units:GetEquipmentId(active.unit,3,1)}
            M.equip()
            assert(not active and state:get(1001)==401000401,'Card grid equip failed')
            assert(units:GetEquipmentId(1001,3,0)==accessories[1] and units:GetEquipmentId(1001,3,1)==accessories[2],'Card equip changed accessories')
            local target=row.screen:GetFocusedItemIndex(2)
            assert(same(row.screen:GetFocusedItemWidget(2),row.button),'Focus lost after card equip')
            row.screen:InputDirection(3,0)
            assert(row.screen:GetFocusedItemIndex(2)==target+1,'Navigation lost after card equip')
            row.screen:InputDirection(2,0)
            FindFirstOf('CPP_GameWidgetInputManager'):HandleInputDecide({});M.tick()
            assert(active,'Card slot could not reopen after equipping')
            close()
            log('Card equip, accessory preservation, close and reopen passed')
            local input=FindFirstOf('CPP_GameWidgetInputManager')
            input:HandleInputCancel({})
            log('Details input target '..row.parent:BP_GetInputTargetWidget():GetFullName())
            input:HandleInputDetail({})
            log('Requested native skill details through normal input')
        end)
    end)
    ExecuteInGameThreadWithDelay(10000,function()
        local found=false
        for _,view in pairs(skillPanels) do
            if view.layout:IsVisible() then
                found=true
                assert(view.unit==1001 and view.cardId==401000401,'Skill details did not follow the equipped card')
                assert(valid(view.image.Brush.ResourceObject),'Skill details artwork missing')
                assert(view.stat:GetText():ToString():find('ATK   +60',1,true),'Skill details maximum stats missing')
                local category=view.layout.WBP_UnitSkillPanelCategoryList:GetPathMenu()
                category:InputDirection(3,0)
                assert(category:GetFocusedItemIndex(2)==1,'Native skill category navigation changed')
                log('Native skill card and maximum stats passed')
                lib('KismetSystemLibrary'):ExecuteConsoleCommand(world,'Shot showui',pc)
            end
        end
        assert(found,'Native skill details did not open')
    end)
    ExecuteInGameThreadWithDelay(13000,function()
        local input=FindFirstOf('CPP_GameWidgetInputManager')
        input:HandleInputCancel({})
        input:HandleInputDetail({})
        for _,view in pairs(skillPanels) do
            if view.layout:IsVisible() then view.layout:SetUnitId(1002) end
        end
    end)
    ExecuteInGameThreadWithDelay(16000,function()
        local found=false
        for _,view in pairs(skillPanels) do
            if view.layout:IsVisible() then
                found=true
                assert(view.unit==1002 and view.cardId==0,'Card details retained the previous character')
                assert(view.name:GetText():ToString()=='None','Empty card details missing')
            end
        end
        assert(found,'Skill details failed to reopen')
        FindFirstOf('CPP_GameWidgetInputManager'):HandleInputCancel({})
        log('Native skill navigation, close, reopen and character changes passed')
        print('[VisionCardProbe] complete\n')
    end)
end
return M
