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
local r=resolve
local manager=r:GetProjectManager()
local project=manager:GetCurrentProject()
assert(project and project:GetName()==expected,'Wrong reference project')
local output='/Users/zgt/agent/resolve-reconstruction/workspace/native-render-20261021-v2'
local report={after={version=r:GetVersionString(),rendering=project:IsRenderingInProgress(),jobs={}},timeline='REA_RENDER_STATUS',completed=true}
for _,job in pairs(project:GetRenderJobList()) do
 if type(job)=='table' and job.TargetDir==output then
  report.after.jobs[#report.after.jobs+1]={job=job,status=project:GetRenderJobStatus(job.JobId)}
 end
end
local t=project:GetCurrentTimeline()
report.after.marker_saved=t:AddMarker(7,'Green','REA_RENDER_STATUS',json(report),1,json(report))
report.after.saved=manager:SaveProject()
print('REA_RENDER_STATUS='..json(report))
