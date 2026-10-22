-- Scope: generated media and newly-created timelines in the dedicated reference project only.
-- No preference changes, original media writes or user timeline edits.
local expected='REA Reference · 2026-10-21'
local media_path='/Users/zgt/agent/resolve-reconstruction/workspace/demo-media/motion.mp4'
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
local m=resolve:GetProjectManager();local p=m:GetCurrentProject()
assert(p and p:GetName()==expected,'Wrong reference project')
local pool=p:GetMediaPool()
local media=pool:ImportMedia({media_path})[1];assert(media)
local t=pool:CreateEmptyTimeline('REA_LINKED_TRIM_START_'..os.date('%Y%m%d_%H%M%S'));assert(t and p:SetCurrentTimeline(t))
local origin=t:GetStartFrame()
pool:AppendToTimeline({{mediaPoolItem=media,startFrame=12,endFrame=60,recordFrame=origin+48,trackIndex=1}})
local v=t:GetItemListInTrack('video',1);local a=t:GetItemListInTrack('audio',1)
assert(#v==1 and #a==1,'Need one video and audio item')
assert(t:SetClipsLinked({v[1],a[1]},true),'Link failed')
resolve:OpenPage('edit');assert(t:SetCurrentTimecode('01:00:03:00'))
local row={action='linked_trim_start_prepare',timeline=t:GetName(),origin=origin,timecode=t:GetCurrentTimecode(),items={}}
for _,kind in ipairs({'video','audio'}) do for _,item in ipairs(t:GetItemListInTrack(kind,1)) do
 local links={};for _,linked in ipairs(item:GetLinkedItems() or {}) do links[#links+1]={id=linked:GetUniqueId(),kind=linked:GetType(),start=linked:GetStart(true),duration=linked:GetDuration(true)} end
 row.items[#row.items+1]={id=item:GetUniqueId(),kind=kind,start=item:GetStart(true),duration=item:GetDuration(true),source_start=item:GetSourceStartFrame(),source_end=item:GetSourceEndFrame(),links=links}
end end
assert(t:AddMarker(0,'Blue','REA_LINKED_TRIM_START_BEFORE',json(row),1,json(row)));m:SaveProject()
print('REA_LINKED_TRIM_START_BEFORE='..json(row))
