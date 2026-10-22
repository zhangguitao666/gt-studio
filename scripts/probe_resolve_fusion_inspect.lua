-- Read existing dedicated synthetic comps; only adds an evidence marker.
local function quote(s)
 return '"'..tostring(s):gsub('[%z\1-\31\\"]',function(c)
  return ({['"']='\\"',['\\']='\\\\',['\n']='\\n',['\r']='\\r',['\t']='\\t'})[c] or string.format('\\u%04x',string.byte(c))
 end)..'"'
end
local function json(x)
 local t=type(x)
 if t=='nil' then return 'null' end
 if t=='string' then return quote(x) end
 if t=='boolean' or t=='number' then return tostring(x) end
 if t~='table' then return quote('<'..t..'>') end
 local keys={};for k,_ in pairs(x) do keys[#keys+1]=k end
 local array=#keys>0
 for _,k in ipairs(keys) do if type(k)~='number' then array=false end end
 local out={}
 if array then for i=1,#x do out[#out+1]=json(x[i]) end;return '['..table.concat(out,',')..']' end
 table.sort(keys,function(a,b)return tostring(a)<tostring(b)end)
 for _,k in ipairs(keys) do out[#out+1]=quote(k)..':'..json(x[k]) end
 return '{'..table.concat(out,',')..'}'
end
local manager=resolve:GetProjectManager();local p=manager:GetCurrentProject()
assert(p and p:GetName()=='REA Reference · 2026-10-21','Wrong reference project')
assert(not p:IsRenderingInProgress(),'Rendering remains active')
local prefix='REA_FUSION_20261022_164830_'
for i=1,p:GetTimelineCount() do
 local t=p:GetTimelineByIndex(i)
 if t:GetName():sub(1,#prefix)==prefix then
  assert(p:SetCurrentTimeline(t));local clip=t:GetItemListInTrack('video',1)[1];local comp=clip:GetFusionCompByIndex(1);assert(comp)
  local row={after={nodes={},pixel_helpers={Pixel=type(Pixel),FuPixel=type(FuPixel)}},timeline=t:GetName(),completed=true}
  for _,node in pairs(comp:GetToolList(false)) do
   local attrs=node:GetAttrs();local item={name=attrs.TOOLS_Name,class=attrs.TOOLS_RegID,inputs={},attributes=attrs}
   for _,input in pairs(node:GetInputList() or {}) do
    local a=input:GetAttrs();local key=a.INPS_ID
    if key then
     local ok,value=pcall(function()return node:GetInput(key)end)
     if ok and (type(value)=='number' or type(value)=='boolean' or type(value)=='string' or type(value)=='table') then item.inputs[key]=value end
    end
   end
   local ok,img=pcall(function()return node.Output:GetValue(comp.CurrentTime)end)
   item.image_read_ok=ok
   if ok and img then
    local aok,ia=pcall(function()return img:GetAttrs()end);if aok then item.image_attributes=ia end
    local pok,pixel=pcall(function()return img:GetPixel(480,90)end)
    item.pixel_call_ok=pok;item.pixel_type=type(pixel)
    if pok and pixel then
     local vok,values=pcall(function()return {r=pixel.R,g=pixel.G,b=pixel.B,a=pixel.A}end)
     if vok then item.rgba=values else item.pixel_read_error=tostring(values) end
    elseif not pok then item.pixel_error=tostring(pixel) end
   end
   row.after.nodes[#row.after.nodes+1]=item
  end
  assert(t:AddMarker(2,'Cyan','REA_FUSION_NODE_INSPECTION',json(row),1,json(row)));manager:SaveProject();print('REA_FUSION_NODE_INSPECTION='..json(row))
 end
end
