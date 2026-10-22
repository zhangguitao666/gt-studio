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
local red=pool:ImportMedia({'/Users/zgt/agent/resolve-reconstruction/workspace/transition-reference/red.mp4'})[1]
local blue=pool:ImportMedia({'/Users/zgt/agent/resolve-reconstruction/workspace/transition-reference/blue.mp4'})[1]
local t=pool:CreateEmptyTimeline('REA_DISSOLVE_UPSTREAM_'..os.date('%Y%m%d_%H%M%S'));assert(t and p:SetCurrentTimeline(t))
local origin=t:GetStartFrame()
for i,media in ipairs({red,blue,red}) do pool:AppendToTimeline({{mediaPoolItem=media,startFrame=12,endFrame=60,recordFrame=origin+(i-1)*48,trackIndex=1}}) end
local v=t:GetItemListInTrack('video',1);assert(#v==3)
table.sort(v,function(a,b)return a:GetStart(true)<b:GetStart(true)end)
assert(v[2]:AddTransition({type='Cross Dissolve',category='simple',position='end',alignment='center',duration=12}))
local function items()
 local out={};for _,i in ipairs(t:GetItemListInTrack('video',1)) do out[#out+1]={kind=i:GetType(),start=i:GetStart(true),duration=i:GetDuration(true)} end;return out
end
local row={action='upstream_clip',ripple=true,timeline='REA_TRANSITION_DELETE_UPSTREAM',completed=true,before=items(),after={}}
row.after.delete_return=t:DeleteClips({v[1]},true);row.after.items=items()
t:AddMarker(0,'Blue','REA_TRANSITION_DELETE_UPSTREAM',json(row),1,json(row));m:SaveProject()
print('REA_TRANSITION_DELETE_UPSTREAM='..json(row))
