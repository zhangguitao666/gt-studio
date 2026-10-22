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
local manager=resolve:GetProjectManager()
local p=manager:GetCurrentProject()
assert(p and p:GetName()==expected,'Wrong reference project')
local source=nil
for i=1,p:GetTimelineCount() do local t=p:GetTimelineByIndex(i);if t:GetName()=='REA_DISSOLVE_20261021_151615_center12' then source=t end end
assert(source,'Missing untouched source reference timeline')
local function items(t,kind)
 local result={}
 for _,v in ipairs(t:GetItemListInTrack(kind,1)) do result[#result+1]={kind=v:GetType(),start=v:GetStart(true),duration=v:GetDuration(true),name=v:GetName()} end
 return result
end
local stamp=os.date('%Y%m%d_%H%M%S')
for _,spec in ipairs({{'clip',false},{'clip',true},{'transition',false}}) do
 local name='REA_DISSOLVE_DELETE_'..stamp..'_'..spec[1]..'_'..tostring(spec[2])
 local t=source:DuplicateTimeline(name);assert(t and p:SetCurrentTimeline(t),'Could not duplicate test timeline')
 local target=nil
 for _,item in ipairs(t:GetItemListInTrack('video',1)) do if (spec[1]=='clip' and item:GetType()=='video') or item:GetType()==spec[1] then target=item;break end end
 assert(target,'Target not found')
 local row={after={},timeline='REA_TRANSITION_DELETE',actual_timeline=name,action=spec[1],ripple=spec[2],before={video=items(t,'video'),audio=items(t,'audio')},completed=true}
 row.after.delete_return=p:GetCurrentTimeline():DeleteClips({target},spec[2])
 row.after.video=items(t,'video');row.after.audio=items(t,'audio')
 t:AddMarker(9,'Red','REA_TRANSITION_DELETE',json(row),1,json(row))
 print('REA_TRANSITION_DELETE='..json(row))
end
manager:SaveProject()
